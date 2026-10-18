"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from pam.config import Settings


@pytest.fixture
def offline_settings(monkeypatch):
    """Keep configuration tests independent of local secrets and overrides."""
    import os

    for name in os.environ:
        if name.startswith("PAM_"):
            monkeypatch.delenv(name)
    return lambda **values: Settings(_env_file=None, **values)


def test_drive_defaults_do_not_create_credentials(
    offline_settings, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    settings = offline_settings()
    assert str(settings.drive_credential_storage_path) == ".pam-drive-credentials.bin"
    assert settings.drive_max_context_chars == 20_000
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [0, -1, 20_001, "invalid"])
def test_drive_context_limit_rejects_invalid_values(offline_settings, value):
    with pytest.raises(ValidationError):
        offline_settings(drive_max_context_chars=value)


@pytest.mark.parametrize("value", [1, 20_000])
def test_drive_context_limit_accepts_environment_bounds(
    offline_settings, monkeypatch, value
):
    monkeypatch.setenv("PAM_DRIVE_MAX_CONTEXT_CHARS", str(value))
    assert offline_settings().drive_max_context_chars == value


def test_drive_credentials_reject_equivalent_paths(offline_settings, tmp_path):
    with pytest.raises(ValidationError, match="storage paths must differ"):
        offline_settings(
            credential_storage_path=tmp_path / "tokens.bin",
            drive_credential_storage_path=tmp_path / "sub" / ".." / "tokens.bin",
        )


def test_production_rejects_missing_secret() -> None:
    with pytest.raises(ValidationError, match="PAM_APP_SECRET is required"):
        Settings(environment="production", app_secret=None)


def test_development_allows_placeholder_configuration() -> None:
    settings = Settings(
        environment="development", _env_file=None, model_provider="fake"
    )

    assert settings.app_secret is None
    assert settings.model_provider == "fake"
