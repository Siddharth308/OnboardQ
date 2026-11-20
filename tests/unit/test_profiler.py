import pandas as pd
import pytest

from app.pipeline.profiler import (
    ColumnType,
    infer_column_type,
    mask_value,
    profile_frame,
)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "22", "-3"], ColumnType.INTEGER),
        (["1.5", "2.0"], ColumnType.DECIMAL),
        (["1", "2.5"], ColumnType.DECIMAL),
        (["a@x.com", "b@y.org"], ColumnType.EMAIL),
        (["true", "No", "yes"], ColumnType.BOOLEAN),
        (["2021-04-03", "2020-01-31"], ColumnType.DATE),
        (["2021-02-30"], ColumnType.STRING),  # invalid calendar date
        (["Asha", "Ravi"], ColumnType.STRING),
        (["", "  "], ColumnType.EMPTY),
    ],
)
def test_infers_column_type(values: list[str], expected: ColumnType) -> None:
    assert infer_column_type(values) is expected


def test_one_odd_value_downgrades_column_to_string() -> None:
    assert infer_column_type(["1", "2", "three"]) is ColumnType.STRING


def test_blank_values_do_not_affect_type() -> None:
    assert infer_column_type(["5", "", "  ", "7"]) is ColumnType.INTEGER


@pytest.mark.xfail(
    strict=True,
    reason="TODO(you): implement ambiguous date handling (see profiler.py)",
)
def test_ambiguous_dates_are_flagged() -> None:
    # "03/04/21" could be 3 April or 4 March. The profile must say so.
    assert infer_column_type(["03/04/21", "17/05/22"]) is ColumnType.DATE


def test_email_samples_keep_only_domain() -> None:
    assert mask_value("asha@acme.com", ColumnType.EMAIL, "Work Email") == "***@acme.com"


def test_personal_name_columns_keep_only_first_character() -> None:
    assert mask_value("Asha Rao", ColumnType.STRING, "Employee Name") == "A***"


def test_company_is_not_mistaken_for_pan() -> None:
    assert mask_value("Acme", ColumnType.STRING, "Company") == "Acme"


def test_profile_reports_stats_and_masks_samples() -> None:
    frame = pd.DataFrame(
        {
            "Staff #": ["S-1", "S-2", "", "S-2"],
            "Full Name": ["Asha Rao", "Ravi Kumar", "Meera", "Meera"],
            "Salary": ["1,000", "", "", "2000"],
        }
    )

    profiles = {p.name: p for p in profile_frame(frame)}

    staff = profiles["Staff #"]
    assert staff.non_null_count == 3
    assert staff.null_rate == 0.25
    assert staff.distinct_count == 2
    assert staff.inferred_type is ColumnType.STRING

    name = profiles["Full Name"]
    assert name.sample_values == ["A***", "R***", "M***"]  # deduplicated, masked

    salary = profiles["Salary"]
    assert salary.null_rate == 0.5
    assert salary.inferred_type is ColumnType.STRING  # "1,000" is not a plain integer


def test_profile_of_empty_frame_has_zero_null_rate() -> None:
    frame = pd.DataFrame({"a": pd.Series([], dtype=str)})

    (profile,) = profile_frame(frame)

    assert profile.null_rate == 0.0
    assert profile.inferred_type is ColumnType.EMPTY
