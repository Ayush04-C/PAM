"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from pam.config import Settings


def test_production_rejects_missing_secret() -> None:
    with pytest.raises(ValidationError, match="PAM_APP_SECRET is required"):
        Settings(environment="production", app_secret=None)


def test_development_allows_placeholder_configuration() -> None:
    settings = Settings(environment="development")

    assert settings.app_secret is None
