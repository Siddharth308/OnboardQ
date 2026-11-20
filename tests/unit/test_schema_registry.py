from pathlib import Path
from typing import get_args

import pytest

from app.pipeline.schema_registry import SchemaRegistry
from app.schemas.mapping import TransformName

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_employee_schema_loads_all_twelve_fields() -> None:
    registry = SchemaRegistry.from_directory(SCHEMAS_DIR)

    schema = registry.get("employee_equity")

    assert schema is not None
    assert len(schema.fields) == 12
    assert all(f.description for f in schema.fields)


def test_every_default_transform_is_in_the_allowed_list() -> None:
    allowed = set(get_args(TransformName))
    schema = SchemaRegistry.from_directory(SCHEMAS_DIR).get("employee_equity")
    assert schema is not None

    assert {f.transform for f in schema.fields} <= allowed


def test_enum_field_declares_its_allowed_values() -> None:
    schema = SchemaRegistry.from_directory(SCHEMAS_DIR).get("employee_equity")
    assert schema is not None

    vesting = next(f for f in schema.fields if f.name == "vesting_schedule")
    assert vesting.allowed_values == ["4Y_1Y_CLIFF", "3Y_MONTHLY", "CUSTOM"]


def test_duplicate_schema_names_are_rejected(tmp_path: Path) -> None:
    body = (
        "name: same\nversion: 1\ndescription: x\nfields:\n"
        "  - name: a\n    type: string\n    description: a\n    transform: trim\n"
    )
    (tmp_path / "one.yaml").write_text(body)
    (tmp_path / "two.yaml").write_text(body)

    with pytest.raises(ValueError, match="Duplicate target schema name"):
        SchemaRegistry.from_directory(tmp_path)


def test_unknown_transform_fails_at_load_time(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "name: bad\nversion: 1\ndescription: x\nfields:\n"
        "  - name: a\n    type: string\n    description: a\n    transform: exec_python\n"
    )

    with pytest.raises(ValueError):
        SchemaRegistry.from_directory(tmp_path)
