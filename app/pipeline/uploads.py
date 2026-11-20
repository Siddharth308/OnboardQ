"""Stream an upload to disk with a hard size cap, without reading it all into memory.

Two checks run in order:
1. The Content-Length header rejects obviously oversized requests before any body is read.
2. Chunks are counted as they are written. The header can be missing or wrong,
   so this count is the real enforcement.
"""

from pathlib import Path

from fastapi import UploadFile

from app.pipeline.parser import FileTooLargeError

CHUNK_SIZE = 64 * 1024
# Multipart framing (boundaries, field names) adds a little on top of the file size.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def check_declared_length(content_length: str | None, max_bytes: int) -> None:
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return  # malformed header: the streaming check still applies
    if declared > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise FileTooLargeError(f"The upload is larger than {max_bytes // (1024 * 1024)} MB.")


async def save_upload_bounded(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Write the upload to `dest` and return its size.

    Aborts and deletes the partial file if the stream exceeds `max_bytes`.
    """
    # Local-disk writes of one 64 KB chunk take microseconds, so they stay on the loop here.
    # Phase 3 moves the whole write to a threadpool if profiling shows it matters.
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLargeError(
                        f"The upload is larger than {max_bytes // (1024 * 1024)} MB."
                    )
                out.write(chunk)
    except FileTooLargeError:
        dest.unlink(missing_ok=True)  # noqa: ASYNC240
        raise
    return written
