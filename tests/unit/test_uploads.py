import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.pipeline.parser import FileTooLargeError
from app.pipeline.uploads import check_declared_length, save_upload_bounded


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="a.csv")


def test_declared_length_over_limit_is_rejected_before_reading() -> None:
    with pytest.raises(FileTooLargeError):
        check_declared_length(str(10 * 1024 * 1024 * 2), max_bytes=10 * 1024 * 1024)


def test_missing_or_malformed_content_length_is_not_rejected_early() -> None:
    check_declared_length(None, max_bytes=10)
    check_declared_length("not-a-number", max_bytes=10)


async def test_save_writes_file_and_returns_size(tmp_path: Path) -> None:
    dest = tmp_path / "out.csv"

    size = await save_upload_bounded(_upload(b"a,b\n1,2\n"), dest, max_bytes=1024)

    assert size == 8
    assert dest.read_bytes() == b"a,b\n1,2\n"


async def test_oversized_stream_is_aborted_and_partial_file_removed(tmp_path: Path) -> None:
    dest = tmp_path / "out.csv"

    with pytest.raises(FileTooLargeError):
        await save_upload_bounded(_upload(b"x" * 200_000), dest, max_bytes=100_000)

    assert not dest.exists()
