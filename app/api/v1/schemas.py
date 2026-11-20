"""Lists the target schemas this deployment knows about."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.pipeline.schema_registry import SchemaRegistry

router = APIRouter(prefix="/v1/schemas", tags=["schemas"])


class SchemaSummary(BaseModel):
    name: str
    version: int
    description: str
    field_count: int


@router.get("", response_model=list[SchemaSummary], summary="List target schemas")
async def list_schemas(request: Request) -> list[SchemaSummary]:
    registry: SchemaRegistry = request.app.state.registry
    return [
        SchemaSummary(
            name=schema.name,
            version=schema.version,
            description=schema.description,
            field_count=len(schema.fields),
        )
        for schema in registry.all()
    ]
