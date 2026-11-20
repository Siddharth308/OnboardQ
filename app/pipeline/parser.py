"""Parse uploaded CSV and XLSX files into a DataFrame of strings.

Everything is read as text (`dtype=str`). Type decisions belong to the profiler
and the transformer, not to pandas guessing. For example, pandas would silently
turn "007" into 7 and "03/04/21" into a date in the wrong format.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

FileKind = Literal["csv", "xlsx"]

# Byte-order marks, checked longest first so UTF-32/UTF-16 are not misread as UTF-8.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)
_DELIMITERS = (",", ";", "\t")
_XLSX_MAGIC = b"PK\x03\x04"  # xlsx is a zip archive


class IngestError(Exception):
    """Domain error for bad input. The API layer maps it to an HTTP status."""

    http_status: ClassVar[int] = 422
    title: ClassVar[str] = "Invalid file"


class UnsupportedFileError(IngestError):
    http_status = 415
    title = "Unsupported file"


class FileTooLargeError(IngestError):
    http_status = 413
    title = "File too large"


class RowLimitExceededError(IngestError):
    http_status = 413
    title = "Too many rows"


class EmptyFileError(IngestError):
    title = "Empty file"


@dataclass(frozen=True)
class ParsedFile:
    frame: pd.DataFrame
    kind: FileKind
    encoding: str | None  # None for xlsx, which is binary
    delimiter: str | None  # None for xlsx


def detect_kind(filename: str, head: bytes) -> FileKind:
    """Decide the format from the extension AND the content. Extensions alone can lie."""
    suffix = Path(filename).suffix.lower()
    is_zip = head.startswith(_XLSX_MAGIC)

    if suffix == ".xlsx":
        if not is_zip:
            raise UnsupportedFileError(
                "File extension is .xlsx but the content is not a spreadsheet."
            )
        return "xlsx"
    if suffix == ".csv":
        if is_zip or b"\x00" in head:
            raise UnsupportedFileError("File extension is .csv but the content is binary.")
        return "csv"
    raise UnsupportedFileError("Only .csv and .xlsx files are accepted.")


def detect_encoding(raw: bytes) -> str:
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            return codec
    # Try strict UTF-8 first. Then cp1252, which covers most Windows exports.
    # latin-1 never fails, so it is the last resort.
    for codec in ("utf-8", "cp1252", "latin-1"):
        try:
            raw.decode(codec)
        except UnicodeDecodeError:
            continue
        return codec
    raise UnsupportedFileError("Could not decode the file as text.")  # unreachable in practice


def detect_delimiter(first_line: str) -> str:
    """Pick the candidate that appears most often in the header line; ties go to comma.

    csv.Sniffer is the stdlib option, but it guesses badly on single-column or
    one-row files. Counting over a known candidate list is simpler and predictable.
    """
    counts = {d: first_line.count(d) for d in _DELIMITERS}
    best = max(_DELIMITERS, key=lambda d: (counts[d], d == ","))
    return best if counts[best] > 0 else ","


def parse_file(path: Path, filename: str, max_rows: int) -> ParsedFile:
    with path.open("rb") as fh:
        head = fh.read(4096)
    kind = detect_kind(filename, head)

    if kind == "xlsx":
        return _parse_xlsx(path, max_rows)
    return _parse_csv(path, max_rows)


def _parse_csv(path: Path, max_rows: int) -> ParsedFile:
    raw = path.read_bytes()
    encoding = detect_encoding(raw)
    text = raw.decode(encoding)  # the utf-8-sig and utf-16 codecs strip the BOM
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = detect_delimiter(first_line)

    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            quoting=csv.QUOTE_MINIMAL,
        )
    except pd.errors.EmptyDataError as exc:
        raise EmptyFileError("The file has no header row.") from exc
    except pd.errors.ParserError as exc:
        raise UnsupportedFileError("The file is not a well-formed CSV.") from exc

    _check_rows(frame, max_rows)
    return ParsedFile(
        frame=_clean_headers(frame), kind="csv", encoding=encoding, delimiter=delimiter
    )


def _parse_xlsx(path: Path, max_rows: int) -> ParsedFile:
    try:
        frame = pd.read_excel(
            path, sheet_name=0, dtype=str, keep_default_na=False, engine="openpyxl"
        )
    except (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError) as exc:
        raise UnsupportedFileError("The spreadsheet could not be read.") from exc

    _check_rows(frame, max_rows)
    return ParsedFile(frame=_clean_headers(frame), kind="xlsx", encoding=None, delimiter=None)


def _check_rows(frame: pd.DataFrame, max_rows: int) -> None:
    if frame.columns.empty:
        raise EmptyFileError("The file has no header row.")
    if len(frame) > max_rows:
        raise RowLimitExceededError(f"The file has more than {max_rows} rows.")


def _clean_headers(frame: pd.DataFrame) -> pd.DataFrame:
    # Trim header whitespace: "Emp ID " and "Emp ID" must be the same column.
    frame = frame.copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame
