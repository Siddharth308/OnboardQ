"""Runs against a real PostgreSQL. Skipped unless ONBOARDIQ_TEST_DATABASE_URL is set.

The test database is wiped, migrated with Alembic (the same path production uses),
then the app runs against it. The SQLite tests cannot prove that the migration and
the Postgres driver work together.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.main import create_app

TEST_URL = os.environ.get("ONBOARDIQ_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(TEST_URL is None, reason="needs ONBOARDIQ_TEST_DATABASE_URL")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def pg_app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    assert TEST_URL is not None
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        # Drop only what this app creates. Dropping the whole schema needs ownership
        # rights that the application role does not have.
        await conn.execute(text("DROP TABLE IF EXISTS jobs, alembic_version"))
    await engine.dispose()

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "app/db/migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_URL)
    # Alembic's env.py calls asyncio.run(), which cannot run inside the test's event
    # loop. A worker thread has no running loop, so this works.
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    settings = Settings(
        environment="test",
        log_level="WARNING",
        database_url=TEST_URL,
        upload_dir=tmp_path / "uploads",
    )
    app = create_app(settings)
    yield app
    await app.state.engine.dispose()


async def test_migration_creates_jobs_table_and_app_works_end_to_end(pg_app: FastAPI) -> None:
    transport = ASGITransport(app=pg_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ready = await client.get("/readyz")
        assert ready.status_code == 200

        upload = await client.post(
            "/v1/jobs",
            files={"file": ("staff.csv", b"Emp ID,Salary\nE1,100\nE2,\n", "text/csv")},
        )
        assert upload.status_code == 202
        job_id = upload.json()["id"]

        profile = await client.get(f"/v1/jobs/{job_id}/profile")
        assert profile.status_code == 200
        salary = next(c for c in profile.json()["columns"] if c["name"] == "Salary")
        assert salary["null_rate"] == 0.5
