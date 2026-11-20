"""Shared fixtures. Factory fixtures keep each test's settings explicit and isolated."""

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: object) -> Settings:
        base: dict[str, object] = {"environment": "test", "log_level": "WARNING"}
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
