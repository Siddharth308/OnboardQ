"""Liveness and readiness endpoints.

- /healthz: the process is up. It does not check dependencies, so a database
  outage never makes the orchestrator restart the container.
- /readyz: the service can take traffic. It runs `SELECT 1` against the database.
  A failure returns 503 with a problem+json body and logs only the exception type.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from structlog import get_logger

from app.core.errors import problem_response

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class HealthStatus(BaseModel):
    status: str


@router.get("/healthz", response_model=HealthStatus)
async def healthz() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/readyz", response_model=HealthStatus, responses={503: {"description": "Not ready"}})
async def readyz(request: Request) -> HealthStatus | JSONResponse:
    factory = request.app.state.session_factory
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        # Log the exception class only. Driver messages can include connection details.
        log.warning("readiness_db_check_failed", error_type=type(exc).__name__)
        return problem_response(request, 503, "Not ready", "The database is unreachable.")
    return HealthStatus(status="ready")
