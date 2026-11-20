"""Liveness and readiness endpoints.

- /healthz: the process is up and serving. No dependencies checked, so a
  broken database never causes the orchestrator to restart the container.
- /readyz: the service can accept traffic. In Phase 1 this only reports app
  state; the database check is added in Phase 2 when the engine exists.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str


@router.get("/healthz", response_model=HealthStatus)
async def healthz() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/readyz", response_model=HealthStatus)
async def readyz() -> HealthStatus:
    return HealthStatus(status="ready")
