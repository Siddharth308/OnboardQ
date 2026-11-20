"""FastAPI application factory.

`create_app()` builds a fresh app on each call. Tests pass custom settings and
get an isolated app, which a module-level global app would not allow.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import health, jobs
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.db.session import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # On shutdown, return pooled DB connections instead of leaking them.
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="OnboardIQ",
        version=settings.version,
        description="AI data onboarding service: maps messy customer files to target schemas.",
        lifespan=lifespan,
    )
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(jobs.router)
    return app


app = create_app()
