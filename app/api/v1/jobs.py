"""Job endpoints: upload (202, background processing), status, profile, and mapping.

Auth and rate limiting are not in this phase yet.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import ProblemError
from app.db.models import Job
from app.db.session import SessionDep
from app.pipeline.parser import IngestError
from app.pipeline.schema_registry import SchemaRegistry
from app.schemas.jobs import JobProfileRead, JobRead
from app.schemas.mapping import MappingProposal
from app.services import jobs as job_service

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

TARGET_SCHEMA_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _registry(request: Request) -> SchemaRegistry:
    registry: SchemaRegistry = request.app.state.registry
    return registry


async def _get_job_or_404(session: SessionDep, job_id: uuid.UUID) -> Job:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ProblemError(404, "Not found", "No job with that id.")
    return job


@router.post(
    "",
    status_code=202,
    response_model=JobRead,
    summary="Upload a CSV or XLSX file; processing runs in the background",
)
async def create_job(
    request: Request,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="CSV or XLSX, max 10 MB by default")],
    target_schema: Annotated[
        str, Form(pattern=TARGET_SCHEMA_PATTERN, examples=["employee_equity"])
    ] = "employee_equity",
) -> Job:
    registry = _registry(request)
    if registry.get(target_schema) is None:
        raise ProblemError(
            422,
            "Unknown target schema",
            f"Known schemas: {', '.join(registry.names())}.",
        )
    try:
        job = await job_service.store_upload(
            session,
            _settings(request),
            file,
            target_schema,
            request.headers.get("content-length"),
        )
    except IngestError as exc:
        raise ProblemError(exc.http_status, exc.title, str(exc)) from exc

    # Runs after the response is sent. It uses its own session and must not touch `session`.
    background_tasks.add_task(
        job_service.run_pipeline,
        job.id,
        _settings(request),
        request.app.state.session_factory,
        registry,
    )
    return job


@router.get("/{job_id}", response_model=JobRead, summary="Get job status")
async def get_job(job_id: uuid.UUID, session: SessionDep) -> Job:
    return await _get_job_or_404(session, job_id)


@router.get("/{job_id}/profile", response_model=JobProfileRead, summary="Get column profile")
async def get_profile(job_id: uuid.UUID, session: SessionDep) -> JobProfileRead:
    job = await _get_job_or_404(session, job_id)
    if job.profile is None or job.row_count is None:
        raise ProblemError(409, "Profile not ready", f"The job is in state {job.status}.")
    return JobProfileRead.from_job(job.id, job.row_count, job.profile)


@router.get("/{job_id}/mapping", response_model=MappingProposal, summary="Get proposed mapping")
async def get_mapping(job_id: uuid.UUID, session: SessionDep) -> MappingProposal:
    job = await _get_job_or_404(session, job_id)
    proposal = job_service.load_proposal(job)
    if proposal is None:
        raise ProblemError(409, "Mapping not ready", f"The job is in state {job.status}.")
    return proposal
