"""Application settings, loaded and validated from environment variables.

Equivalent in spirit to parsing `process.env` with Zod at boot: a missing or
malformed value fails the process at startup, not on the first request.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ONBOARDIQ_",
        extra="ignore",
    )

    app_name: str = "onboardiq"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    version: str = "0.1.0"

    # Secrets are SecretStr so they never leak into reprs or logs.
    api_key: SecretStr = SecretStr("dev-only-change-me")

    database_url: str = "postgresql+asyncpg://onboardiq:onboardiq@localhost:5432/onboardiq"

    max_upload_mb: int = Field(default=10, ge=1, le=100)
    max_upload_rows: int = Field(default=50_000, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()
