"""Column profiling: per-column stats and PII-masked sample values.

The profile is what the LLM will later see (Phase 4), so masking happens here,
at the source, not in each caller.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import pandas as pd

SAMPLE_SIZE = 5
MAX_SAMPLE_CHARS = 40

_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL = re.compile(r"^[+-]?\d+(\.\d+)?$")  # also matches integers; INTEGER is checked first
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BOOLEAN_TOKENS = frozenset({"true", "false", "yes", "no"})
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Header tokens that mark a column as personal data. Matched as whole tokens, so
# "company" does not match "pan".
_PII_TOKENS = frozenset({"name", "email", "mail", "phone", "mobile", "ssn", "dob", "birth", "pan"})


class ColumnType(StrEnum):
    EMPTY = "empty"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    EMAIL = "email"
    BOOLEAN = "boolean"
    STRING = "string"


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    position: int
    non_null_count: int
    null_rate: float
    distinct_count: int
    inferred_type: ColumnType
    sample_values: list[str]


def is_blank(value: str) -> bool:
    return value.strip() == ""


def infer_column_type(values: Sequence[str]) -> ColumnType:
    """Infer one type for a column from its non-blank values.

    Every non-blank value must match a type for the column to get it. Otherwise
    the column falls back to STRING.
    """
    present = [v.strip() for v in values if not is_blank(v)]
    if not present:
        return ColumnType.EMPTY

    checks: tuple[tuple[ColumnType, re.Pattern[str] | frozenset[str] | None], ...] = (
        (ColumnType.INTEGER, _INTEGER),
        (ColumnType.DECIMAL, _DECIMAL),
        (ColumnType.EMAIL, _EMAIL),
        (ColumnType.BOOLEAN, _BOOLEAN_TOKENS),
        (ColumnType.DATE, _ISO_DATE),
    )
    for column_type, rule in checks:
        if all(_matches(v, rule) for v in present):
            return column_type

    # TODO(you): add dates in the ambiguous formats from the spec, e.g. "03/04/21"
    # (day-first or month-first?), "04-Mar-2021" and "2021/04/03". Decide how to
    # handle ambiguity: a column where every value has day <= 12 is ambiguous. Would
    # you return DATE with a flag, or leave it STRING and let the LLM decide? Add
    # the tests in tests/test_profiler.py. The test
    # test_ambiguous_dates_are_flagged is marked xfail until you implement it.
    return ColumnType.STRING


def _matches(value: str, rule: re.Pattern[str] | frozenset[str] | None) -> bool:
    if isinstance(rule, frozenset):
        return value.lower() in rule
    if rule is None:
        return False
    if rule is _ISO_DATE:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return rule.match(value) is not None


def _is_pii_column(name: str) -> bool:
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    return bool(tokens & _PII_TOKENS)


def mask_value(value: str, column_type: ColumnType, column_name: str) -> str:
    """Mask one sample value.

    Emails keep only the domain. Personal-data columns keep one character.
    """
    value = value.strip()
    if column_type is ColumnType.EMAIL and "@" in value:
        return "***@" + value.rsplit("@", 1)[1]
    if _is_pii_column(column_name):
        return value[:1] + "***" if value else value
    return value[:MAX_SAMPLE_CHARS]


def profile_frame(frame: pd.DataFrame) -> list[ColumnProfile]:
    total_rows = len(frame)
    profiles: list[ColumnProfile] = []

    for position, name in enumerate(frame.columns):
        raw_values = [str(v) for v in frame[name].tolist()]
        present = [v for v in raw_values if not is_blank(v)]
        column_type = infer_column_type(raw_values)

        samples: list[str] = []
        seen: set[str] = set()
        for value in present:
            if value in seen:
                continue
            seen.add(value)
            samples.append(mask_value(value, column_type, str(name)))
            if len(samples) == SAMPLE_SIZE:
                break

        null_count = total_rows - len(present)
        profiles.append(
            ColumnProfile(
                name=str(name),
                position=position,
                non_null_count=len(present),
                null_rate=round(null_count / total_rows, 4) if total_rows else 0.0,
                distinct_count=len(set(present)),
                inferred_type=column_type,
                sample_values=samples,
            )
        )
    return profiles
