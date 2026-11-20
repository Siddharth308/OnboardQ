from pathlib import Path

import pytest
from openpyxl import Workbook

from app.pipeline.parser import (
    EmptyFileError,
    RowLimitExceededError,
    UnsupportedFileError,
    detect_delimiter,
    detect_encoding,
    detect_kind,
    parse_file,
)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_detects_utf8_bom_and_strips_it_from_headers(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", "﻿Emp ID,Name\n1,Asha\n".encode())

    parsed = parse_file(path, "a.csv", max_rows=100)

    assert parsed.encoding == "utf-8-sig"
    assert list(parsed.frame.columns) == ["Emp ID", "Name"]


def test_falls_back_to_cp1252_for_non_utf8_text(tmp_path: Path) -> None:
    # "Zoë" is valid cp1252 but not valid UTF-8.
    path = _write(tmp_path, "a.csv", "Name,City\nZoë,Köln\n".encode("cp1252"))

    parsed = parse_file(path, "a.csv", max_rows=100)

    assert parsed.encoding == "cp1252"
    assert parsed.frame.iloc[0]["Name"] == "Zoë"


@pytest.mark.parametrize(
    ("delimiter", "header"),
    [(";", "a;b;c"), ("\t", "a\tb\tc"), (",", "a,b,c")],
)
def test_detects_delimiter(tmp_path: Path, delimiter: str, header: str) -> None:
    body = delimiter.join(["1", "2", "3"])
    path = _write(tmp_path, "a.csv", f"{header}\n{body}\n".encode())

    parsed = parse_file(path, "a.csv", max_rows=100)

    assert parsed.delimiter == delimiter
    assert list(parsed.frame.columns) == ["a", "b", "c"]


def test_values_are_read_as_text_so_leading_zeros_survive(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", b"employee_id,grant\n007,1e3\n")

    frame = parse_file(path, "a.csv", max_rows=100).frame

    assert frame.iloc[0]["employee_id"] == "007"
    assert frame.iloc[0]["grant"] == "1e3"


def test_empty_cells_are_empty_strings_not_nan(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", b"a,b\n1,\nNA,x\n")

    frame = parse_file(path, "a.csv", max_rows=100).frame

    assert frame.iloc[0]["b"] == ""
    assert frame.iloc[1]["a"] == "NA"  # not treated as a missing value


def test_headers_are_trimmed(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", b" Emp ID , Name \n1,2\n")

    frame = parse_file(path, "a.csv", max_rows=100).frame

    assert list(frame.columns) == ["Emp ID", "Name"]


def test_parses_xlsx(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Staff #", "Grant"])
    sheet.append(["S-1", 100])
    path = tmp_path / "a.xlsx"
    workbook.save(path)

    parsed = parse_file(path, "a.xlsx", max_rows=100)

    assert parsed.kind == "xlsx"
    assert list(parsed.frame.columns) == ["Staff #", "Grant"]
    assert parsed.frame.iloc[0]["Staff #"] == "S-1"


def test_rejects_xlsx_extension_with_csv_content(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.xlsx", b"a,b\n1,2\n")

    with pytest.raises(UnsupportedFileError):
        parse_file(path, "a.xlsx", max_rows=100)


def test_rejects_csv_extension_with_binary_content(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", b"a,b\n\x00\x01,2\n")

    with pytest.raises(UnsupportedFileError):
        parse_file(path, "a.csv", max_rows=100)


def test_rejects_unknown_extension() -> None:
    with pytest.raises(UnsupportedFileError):
        detect_kind("payload.exe", b"MZ")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.csv", b"")

    with pytest.raises(EmptyFileError):
        parse_file(path, "a.csv", max_rows=100)


def test_row_limit_is_enforced(tmp_path: Path) -> None:
    rows = "\n".join(f"{i},x" for i in range(5))
    path = _write(tmp_path, "a.csv", f"id,v\n{rows}\n".encode())

    with pytest.raises(RowLimitExceededError):
        parse_file(path, "a.csv", max_rows=4)


def test_detect_encoding_prefers_utf8_for_plain_ascii() -> None:
    assert detect_encoding(b"plain ascii") == "utf-8"


def test_detect_delimiter_defaults_to_comma_when_no_candidate_present() -> None:
    assert detect_delimiter("single column") == ","
