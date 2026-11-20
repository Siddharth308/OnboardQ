"""Job endpoints: upload, status, and column profile.

Auth, rate limiting and async processing are not in Phase 2. Phase 3 changes
POST to return 202 and run the work in the background.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import ProblemError
from app.db.models import Job
from app.db.session import SessionDep
from app.pipeline.parser import IngestError
from app.schemas.jobs import JobProfileRead, JobRead
from app.services import jobs as job_service

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

TARGET_SCHEMA_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post("", status_code=201, response_model=JobRead, summary="Upload a CSV or XLSX file")
async def create_job(
    request: Request,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="CSV or XLSX, max 10 MB by default")],
    target_schema: Annotated[
        str, Form(pattern=TARGET_SCHEMA_PATTERN, examples=["employee_equity"])
    ] = "employee_equity",
) -> Job:
    try:
        return await job_service.create_job(
            session,
            _settings(request),
            file,
            target_schema,
            request.headers.get("content-length"),
        )
    except IngestError as exc:
        raise ProblemError(exc.http_status, exc.title, str(exc)) from exc


@router.get("/{job_id}", response_model=JobRead, summary="Get job status")
async def get_job(job_id: uuid.UUID, session: SessionDep) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise ProblemError(404, "Not found", "No job with that id.")
    return job


@router.get("/{job_id}/profile", response_model=JobProfileRead, summary="Get column profile")
async def get_profile(job_id: uuid.UUID, session: SessionDep) -> JobProfileRead:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ProblemError(404, "Not found", "No job with that id.")
    if job.profile is None or job.row_count is None:
        raise ProblemError(409, "Profile not ready", f"The job is in state {job.status}.")
    return JobProfileRead.from_job(job.id, job.row_count, job.profile)
