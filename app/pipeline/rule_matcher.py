"""Rule-based column matching: exact name, known synonym, then fuzzy similarity.

Rules run before any LLM call. Easy columns are resolved here for free and
deterministically, so the LLM only sees what the rules cannot resolve.
"""

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from app.pipeline.schema_registry import TargetField, TargetSchema
from app.schemas.mapping import FieldMapping, MappingProposal

FUZZY_THRESHOLD = 88  # rapidfuzz scores run 0-100
AMBIGUITY_MARGIN = 6  # if a second target scores this close, do not guess
EXACT_CONFIDENCE = 1.0
SYNONYM_CONFIDENCE = 0.95

MatchMethod = Literal["exact", "synonym", "fuzzy"]


def normalize(text: str) -> str:
    """'Emp ID', 'emp_id' and 'EMP-ID' all become 'empid'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Match:
    target_field: str
    source_column: str
    method: MatchMethod
    confidence: float


@dataclass(frozen=True)
class MatchResult:
    matches: list[Match]
    unresolved_targets: list[str]
    unmapped_sources: list[str]


def _candidates(field: TargetField) -> dict[str, MatchMethod]:
    """Normalized names this field answers to, mapped to how a match would be classified."""
    names: dict[str, MatchMethod] = {normalize(field.name): "exact"}
    for synonym in field.synonyms:
        names.setdefault(normalize(synonym), "synonym")
    return names


def match_columns(columns: list[str], schema: TargetSchema) -> MatchResult:
    fields = {f.name: f for f in schema.fields}
    candidates = {name: _candidates(f) for name, f in fields.items()}
    unresolved = set(fields)
    used_sources: set[str] = set()
    matches: list[Match] = []

    def accept(target: str, source: str, method: MatchMethod, confidence: float) -> None:
        matches.append(Match(target, source, method, confidence))
        unresolved.discard(target)
        used_sources.add(source)

    # Pass 1: exact name and synonym matches. Column order breaks ties deterministically.
    for source in columns:
        key = normalize(source)
        for target in sorted(unresolved):
            method = candidates[target].get(key)
            if method is None or source in used_sources:
                continue
            if method == "exact":
                accept(target, source, "exact", EXACT_CONFIDENCE)
            else:
                accept(target, source, "synonym", SYNONYM_CONFIDENCE)
            break

    # Pass 2: fuzzy matches above threshold. Strongest pairs first. Skip a pair if the
    # column also scores almost as well against another target, because guessing wrong
    # is worse than leaving the column to the LLM or a reviewer.
    scored: list[tuple[float, str, str]] = []
    for source in columns:
        if source in used_sources:
            continue
        key = normalize(source)
        for target in unresolved:
            best = max(fuzz.ratio(key, c) for c in candidates[target])
            if best >= FUZZY_THRESHOLD:
                scored.append((best, target, source))

    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    for best, target, source in scored:
        if target not in unresolved or source in used_sources:
            continue
        rivals = [
            max(fuzz.ratio(normalize(source), c) for c in candidates[other])
            for other in unresolved
            if other != target
        ]
        if any(score >= best - AMBIGUITY_MARGIN for score in rivals):
            continue
        accept(target, source, "fuzzy", round(best / 100, 2))

    return MatchResult(
        matches=sorted(matches, key=lambda m: columns.index(m.source_column)),
        unresolved_targets=sorted(unresolved),
        unmapped_sources=[c for c in columns if c not in used_sources],
    )


def build_proposal(columns: list[str], schema: TargetSchema) -> MappingProposal:
    result = match_columns(columns, schema)
    fields = {f.name: f for f in schema.fields}
    by_target = {m.target_field: m for m in result.matches}

    mappings: list[FieldMapping] = []
    for field in schema.fields:
        match = by_target.get(field.name)
        if match is None:
            mappings.append(
                FieldMapping(
                    target_field=field.name,
                    source_columns=[],
                    transform=field.transform,
                    confidence=0.0,
                    reasoning="No rule matched. Needs the LLM step or human review.",
                )
            )
            continue
        mappings.append(
            FieldMapping(
                target_field=field.name,
                source_columns=[match.source_column],
                transform=field.transform,
                confidence=match.confidence,
                reasoning=_reasoning(match.method, match.source_column, field),
            )
        )

    missing = [name for name in result.unresolved_targets if fields[name].required]
    return MappingProposal(
        target_schema=schema.name,
        mappings=mappings,
        unmapped_source_columns=result.unmapped_sources,
        missing_required_fields=sorted(missing),
    )


def _reasoning(method: MatchMethod, source: str, field: TargetField) -> str:
    if method == "exact":
        return f"Header '{source}' matches the field name exactly."
    if method == "synonym":
        return f"Header '{source}' is a known alias for '{field.name}'."
    return f"Header '{source}' is similar to '{field.name}' (fuzzy match)."
