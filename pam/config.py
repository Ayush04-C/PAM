"""Typed application configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from PAM_-prefixed environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PAM_")

    environment: Literal["development", "production"] = "development"
    app_secret: SecretStr | None = None

    @model_validator(mode="after")
    def require_production_secret(self) -> Settings:
        """Require a secret only when running in production."""
        if self.environment == "production" and self.app_secret is None:
            raise ValueError("PAM_APP_SECRET is required in production")
        return self
