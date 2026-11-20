"""Mapping models. These are also the structured-output schema the LLM must fill (Phase 4)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

TransformName = Literal[
    "rename",
    "split_full_name",
    "concat",
    "parse_date",
    "strip_currency",
    "to_int",
    "to_decimal",
    "map_enum",
    "normalize_country",
    "lowercase",
    "trim",
    "constant",
    "ignore",
]


class FieldMapping(BaseModel):
    target_field: str
    source_columns: list[str]  # empty when the field is unresolved
    transform: TransformName
    transform_params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    reasoning: str  # short, human-readable; never contains cell values


class MappingProposal(BaseModel):
    target_schema: str
    method: Literal["rules"] = "rules"  # Phase 4 adds "rules+llm"
    mappings: list[FieldMapping]
    unmapped_source_columns: list[str]
    missing_required_fields: list[str]
