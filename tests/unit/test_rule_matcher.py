from pathlib import Path

import pytest

from app.pipeline.rule_matcher import build_proposal, match_columns, normalize
from app.pipeline.schema_registry import SchemaRegistry, TargetField, TargetSchema

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


@pytest.fixture(scope="module")
def employee_schema() -> TargetSchema:
    schema = SchemaRegistry.from_directory(SCHEMAS_DIR).get("employee_equity")
    assert schema is not None
    return schema


def _field(name: str, synonyms: list[str] | None = None, required: bool = True) -> TargetField:
    return TargetField(
        name=name,
        type="string",
        required=required,
        description=f"{name} field",
        synonyms=synonyms or [],
        transform="trim",
    )


def _schema(*fields: TargetField) -> TargetSchema:
    return TargetSchema(name="test", version=1, description="test", fields=list(fields))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Emp ID", "empid"),
        ("employee_id", "employeeid"),
        ("EMP-ID ", "empid"),
        ("Staff #", "staff"),
    ],
)
def test_normalize_ignores_case_and_punctuation(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_exact_field_names_match_with_full_confidence(employee_schema: TargetSchema) -> None:
    columns = [
        "employee_id", "first_name", "last_name", "email", "date_of_joining", "grant_id",
        "grant_date", "options_granted", "exercise_price", "vesting_schedule", "country",
    ]  # fmt: skip

    result = match_columns(columns, employee_schema)

    assert len(result.matches) == 11
    assert all(m.method == "exact" and m.confidence == 1.0 for m in result.matches)
    assert result.unresolved_targets == ["department"]  # the only optional field
    assert result.unmapped_sources == []


def test_messy_headers_resolve_through_synonyms(employee_schema: TargetSchema) -> None:
    columns = ["Emp ID", "Work Email", "DOJ", "Grant No", "Strike Price", "Country Code"]

    result = match_columns(columns, employee_schema)

    by_target = {m.target_field: m for m in result.matches}
    assert by_target["employee_id"].source_column == "Emp ID"
    assert by_target["employee_id"].method == "synonym"
    assert by_target["email"].source_column == "Work Email"
    assert by_target["date_of_joining"].source_column == "DOJ"
    assert by_target["exercise_price"].source_column == "Strike Price"
    assert by_target["country"].source_column == "Country Code"


def test_close_typo_resolves_fuzzily_with_lower_confidence(employee_schema: TargetSchema) -> None:
    result = match_columns(["Employe ID"], employee_schema)

    (match,) = result.matches
    assert match.target_field == "employee_id"
    assert match.method == "fuzzy"
    assert 0.88 <= match.confidence <= 0.95


def test_ambiguous_fuzzy_match_is_not_guessed() -> None:
    # "startdatex" is about equally similar to both targets, so the rules must abstain.
    schema = _schema(_field("start_date_a"), _field("start_date_b"))

    result = match_columns(["start_date_x"], schema)

    assert result.matches == []
    assert result.unresolved_targets == ["start_date_a", "start_date_b"]
    assert result.unmapped_sources == ["start_date_x"]


def test_one_source_column_never_fills_two_fields() -> None:
    schema = _schema(_field("employee_id", ["emp id"]), _field("staff_id", ["emp id"]))

    result = match_columns(["Emp ID"], schema)

    assert len(result.matches) == 1
    assert result.unmapped_sources == []


def test_first_column_wins_when_two_columns_match_the_same_field() -> None:
    schema = _schema(_field("employee_id"))

    result = match_columns(["EmployeeID", "employee_id"], schema)

    assert [m.source_column for m in result.matches] == ["EmployeeID"]
    assert result.unmapped_sources == ["employee_id"]


def test_proposal_flags_missing_required_fields(employee_schema: TargetSchema) -> None:
    proposal = build_proposal(["Emp ID", "Full Name"], employee_schema)

    assert "email" in proposal.missing_required_fields
    assert "employee_id" not in proposal.missing_required_fields
    assert "department" not in proposal.missing_required_fields  # optional
    assert proposal.unmapped_source_columns == ["Full Name"]


def test_every_target_field_appears_in_proposal(employee_schema: TargetSchema) -> None:
    proposal = build_proposal(["Emp ID"], employee_schema)

    assert {m.target_field for m in proposal.mappings} == {f.name for f in employee_schema.fields}
    unresolved = [m for m in proposal.mappings if not m.source_columns]
    assert all(m.confidence == 0.0 for m in unresolved)


def test_reasoning_names_headers_but_never_sample_values(employee_schema: TargetSchema) -> None:
    proposal = build_proposal(["Work Email"], employee_schema)

    (email,) = [m for m in proposal.mappings if m.target_field == "email"]
    assert "Work Email" in email.reasoning
    assert "@" not in email.reasoning  # no data from the file leaks into the reasoning


def test_matching_is_deterministic(employee_schema: TargetSchema) -> None:
    columns = ["Emp ID", "Work Email", "Joined", "Grant Dt", "Options"]

    first = match_columns(columns, employee_schema)
    second = match_columns(columns, employee_schema)

    assert first == second
