"""ORM models. Phase 2 creates only the `jobs` table; mappings and rows come later."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored as a string, not a DB enum: adding a state later is a plain code change,
    # not an ALTER TYPE migration. Transitions are enforced in the service layer.
    status: Mapped[str] = mapped_column(String(32), index=True)
    target_schema: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(512))
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Column profile, already PII-masked. Never raw cell values.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Proposed mapping (MappingProposal JSON). Written by the rule matcher, later the LLM.
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Python-side defaults, not SQL expressions. A SQL default leaves the attribute
    # expired after flush, and reading it in async code then fails with MissingGreenlet.
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
