"""FastAPI application factory.

`create_app()` builds a fresh app on each call. Tests pass custom settings and
get an isolated app, which a module-level global app would not allow.
"""

from fastapi import FastAPI

from app.api.v1 import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="OnboardIQ",
        version=settings.version,
        description="AI data onboarding service: maps messy customer files to target schemas.",
    )
    app.state.settings = settings
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    return app


app = create_app()
