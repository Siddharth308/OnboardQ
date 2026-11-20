"""API response models for jobs. Separate from the ORM models on purpose:
the API contract can change without touching the database schema."""

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    target_schema: str
    filename: str
    size_bytes: int
    row_count: int | None
    column_count: int | None
    error_reason: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ColumnProfileRead(BaseModel):
    name: str
    position: int
    non_null_count: int
    null_rate: float
    distinct_count: int
    inferred_type: str
    sample_values: list[str]


class JobProfileRead(BaseModel):
    job_id: uuid.UUID
    row_count: int
    column_count: int
    encoding: str | None
    delimiter: str | None
    file_kind: str
    columns: list[ColumnProfileRead]

    @classmethod
    def from_job(
        cls, job_id: uuid.UUID, row_count: int, profile: dict[str, Any]
    ) -> "JobProfileRead":
        return cls(
            job_id=job_id,
            row_count=row_count,
            column_count=len(profile["columns"]),
            encoding=profile["encoding"],
            delimiter=profile["delimiter"],
            file_kind=profile["file_kind"],
            columns=[ColumnProfileRead(**c) for c in profile["columns"]],
        )
