"""Target schemas loaded from YAML.

Each file is one schema, so supporting a new domain is a new file.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.schemas.mapping import TransformName

FieldType = Literal["string", "email", "date", "integer", "decimal", "enum", "country"]


class TargetField(BaseModel):
    name: str
    type: FieldType
    required: bool = False
    unique: bool = False
    description: str
    synonyms: list[str] = Field(default_factory=list)
    allowed_values: list[str] = Field(default_factory=list)
    transform: TransformName


class TargetSchema(BaseModel):
    name: str
    version: int
    description: str
    fields: list[TargetField]


class SchemaRegistry:
    def __init__(self, schemas: dict[str, TargetSchema]) -> None:
        self._schemas = schemas

    @classmethod
    def from_directory(cls, directory: Path) -> "SchemaRegistry":
        schemas: dict[str, TargetSchema] = {}
        for path in sorted(directory.glob("*.yaml")):
            with path.open(encoding="utf-8") as fh:
                # safe_load, never yaml.load: YAML can otherwise construct arbitrary objects.
                raw: object = yaml.safe_load(fh)
            schema = TargetSchema.model_validate(raw)
            if schema.name in schemas:
                raise ValueError(f"Duplicate target schema name: {schema.name}")
            schemas[schema.name] = schema
        return cls(schemas)

    def get(self, name: str) -> TargetSchema | None:
        return self._schemas.get(name)

    def names(self) -> list[str]:
        return sorted(self._schemas)

    def all(self) -> list[TargetSchema]:
        return [self._schemas[name] for name in self.names()]
