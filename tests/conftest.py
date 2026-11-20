"""Shared fixtures. Factory fixtures keep each test's settings explicit and isolated."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.models import Base
from app.main import create_app


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    def _make(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "environment": "test",
            "log_level": "WARNING",
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            "upload_dir": tmp_path / "uploads",
        }
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    return _make


@pytest.fixture
async def app(make_settings: Callable[..., Settings]) -> AsyncIterator[FastAPI]:
    application = create_app(make_settings())
    engine: AsyncEngine = application.state.engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield application
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
