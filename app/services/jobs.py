"""Job orchestration: state transitions, the upload step, and the background pipeline.

Request path: store the file and create the job (UPLOADED), then return 202.
Background path: PROFILING → MAPPING → AWAITING_REVIEW, or FAILED with a reason.

The background task opens its own DB session. The request's session is closed
by the time the task runs, so it must not be reused.
"""

import uuid
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Job
from app.pipeline.parser import IngestError, UnsupportedFileError, parse_file
from app.pipeline.profiler import ColumnProfile, profile_frame
from app.pipeline.rule_matcher import build_proposal
from app.pipeline.schema_registry import SchemaRegistry
from app.pipeline.uploads import check_declared_length, save_upload_bounded
from app.schemas.mapping import MappingProposal

log = structlog.get_logger(__name__)

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


# Allowed forward transitions. Any non-terminal state may also move to FAILED.
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
        if current in (JobStatus.COMPLETED, JobStatus.FAILED):
            raise InvalidTransitionError(f"A {current} job cannot fail.")
    elif to not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Cannot move from {current} to {to}.")
    job.status = to.value


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


async def store_upload(
    session: AsyncSession,
    settings: Settings,
    upload: UploadFile,
    target_schema: str,
    content_length: str | None,
) -> Job:
    """Save the file and create an UPLOADED job. Parsing happens later, in the background."""
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
    return job


async def run_pipeline(
    job_id: uuid.UUID,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    registry: SchemaRegistry,
) -> None:
    """Parse, profile, and propose a mapping for one job.

    Idempotent: a job that has already left UPLOADED is skipped, so a retried task
    cannot process the same file twice.
    """
    structlog.contextvars.bind_contextvars(job_id=str(job_id))
    try:
        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != JobStatus.UPLOADED.value:
                log.info("pipeline_skipped", reason="not_in_uploaded_state")
                return

            try:
                await _run_stages(job, session, settings, registry)
            except Exception as exc:
                # Log the exception class only. Messages from pandas or the DB can
                # include cell values or connection details.
                log.exception("pipeline_failed", error_type=type(exc).__name__)
                job.error_reason = _failure_reason(exc)
                transition(job, JobStatus.FAILED)
                await session.commit()
    finally:
        structlog.contextvars.unbind_contextvars("job_id")


async def _run_stages(
    job: Job, session: AsyncSession, settings: Settings, registry: SchemaRegistry
) -> None:
    schema = registry.get(job.target_schema)
    if schema is None:
        raise UnsupportedFileError(f"Unknown target schema '{job.target_schema}'.")

    transition(job, JobStatus.PROFILING)
    await session.commit()
    log.info("stage_started", stage="profile")

    # Parsing and profiling are CPU-bound pandas work. Running them directly in this
    # coroutine would block the event loop for every other request.
    parsed = await run_in_threadpool(
        parse_file, Path(job.storage_path), job.filename, settings.max_upload_rows
    )
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
    log.info("stage_finished", stage="profile", rows=job.row_count, columns=job.column_count)

    transition(job, JobStatus.MAPPING)
    await session.commit()
    log.info("stage_started", stage="rule_match")

    proposal = build_proposal([p.name for p in profiles], schema)
    job.mapping = proposal.model_dump(mode="json")
    transition(job, JobStatus.AWAITING_REVIEW)
    await session.commit()
    log.info(
        "stage_finished",
        stage="rule_match",
        matched=sum(1 for m in proposal.mappings if m.source_columns),
        missing_required=len(proposal.missing_required_fields),
    )


def load_proposal(job: Job) -> MappingProposal | None:
    if job.mapping is None:
        return None
    return MappingProposal.model_validate(job.mapping)


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, IngestError):
        return str(exc)
    return "Processing failed. The file could not be completed."


def _serialize(profile: ColumnProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["inferred_type"] = profile.inferred_type.value
    return data
