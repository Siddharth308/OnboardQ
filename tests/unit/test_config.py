import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_applied() -> None:
    settings = Settings()

    assert settings.environment == "dev"
    assert settings.max_upload_mb == 10


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONBOARDIQ_ENVIRONMENT", "prod")
    monkeypatch.setenv("ONBOARDIQ_MAX_UPLOAD_MB", "25")

    settings = Settings()

    assert settings.environment == "prod"
    assert settings.max_upload_mb == 25


def test_invalid_value_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONBOARDIQ_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_api_key_is_not_leaked_in_repr() -> None:
    settings = Settings(api_key="super-secret-value")  # type: ignore[arg-type]

    assert "super-secret-value" not in repr(settings)
