"""Job orchestration: upload → profile, with explicit state transitions.

Phase 2 runs parsing and profiling inside the request. Phase 3 moves this
work to a background task. The state machine and the storage layout stay the same.
"""

import uuid
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Job
from app.pipeline.parser import IngestError, UnsupportedFileError, parse_file
from app.pipeline.profiler import ColumnProfile, profile_frame
from app.pipeline.uploads import check_declared_length, save_upload_bounded

ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx"})


class JobStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROFILING = "PROFILING"
    MAPPING = "MAPPING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    TRANSFORMING = "TRANSFORMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Allowed transitions. Any state may also move to FAILED (checked separately).
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.UPLOADED: frozenset({JobStatus.PROFILING}),
    JobStatus.PROFILING: frozenset({JobStatus.MAPPING}),
    JobStatus.MAPPING: frozenset({JobStatus.AWAITING_REVIEW}),
    JobStatus.AWAITING_REVIEW: frozenset({JobStatus.APPROVED}),
    JobStatus.APPROVED: frozenset({JobStatus.TRANSFORMING}),
    JobStatus.TRANSFORMING: frozenset({JobStatus.COMPLETED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class InvalidTransitionError(Exception):
    pass


def transition(job: Job, to: JobStatus) -> None:
    current = JobStatus(job.status)
    if to is JobStatus.FAILED:
        if current is JobStatus.COMPLETED:
            raise InvalidTransitionError("A completed job cannot fail.")
    elif to not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Cannot move from {current} to {to}.")
    job.status = to.value


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


async def create_job(
    session: AsyncSession,
    settings: Settings,
    upload: UploadFile,
    target_schema: str,
    content_length: str | None,
) -> Job:
    filename = Path(upload.filename or "upload").name  # drop any client-supplied directories
    if _ext(filename) not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError("Only .csv and .xlsx files are accepted.")
    check_declared_length(content_length, settings.max_upload_bytes)

    job_id = uuid.uuid4()
    storage_path = settings.upload_dir / f"{job_id}{_ext(filename)}"
    size = await save_upload_bounded(upload, storage_path, settings.max_upload_bytes)

    job = Job(
        id=job_id,
        status=JobStatus.UPLOADED.value,
        target_schema=target_schema,
        filename=filename,
        content_type=upload.content_type,
        size_bytes=size,
        storage_path=str(storage_path),
    )
    session.add(job)
    await session.commit()

    transition(job, JobStatus.PROFILING)
    await session.commit()

    try:
        parsed = await run_in_threadpool(
            parse_file, storage_path, filename, settings.max_upload_rows
        )
    except IngestError as exc:
        transition(job, JobStatus.FAILED)
        job.error_reason = str(exc)
        await session.commit()
        raise

    profiles = profile_frame(parsed.frame)
    job.row_count = len(parsed.frame)
    job.column_count = len(profiles)
    job.profile = {
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "file_kind": parsed.kind,
        "columns": [_serialize(p) for p in profiles],
    }
    await session.commit()
    return job


def _serialize(profile: ColumnProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["inferred_type"] = profile.inferred_type.value
    return data
