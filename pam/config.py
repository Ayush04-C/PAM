"""Typed application configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from PAM_-prefixed environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PAM_")

    environment: Literal["development", "production"] = "development"
    app_secret: SecretStr | None = None
    calendar_backend: Literal["fake", "google"] = "fake"
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    credential_encryption_key: SecretStr | None = None
    credential_storage_path: Path = Path(".pam-google-credentials.bin")
    model_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    conversation_debug_tool_calls: bool = False
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_user_ids: tuple[int, ...] = ()

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_telegram_user_ids(cls, value: object) -> object:
        """Accept a concise comma-separated numeric user-ID allowlist."""
        if isinstance(value, int):
            return (value,)
        if isinstance(value, str):
            try:
                return tuple(
                    int(item.strip()) for item in value.split(",") if item.strip()
                )
            except ValueError as error:
                raise ValueError(
                    "TELEGRAM_ALLOWED_USER_IDS must contain integers"
                ) from error
        return value

    @model_validator(mode="after")
    def require_production_secret(self) -> Settings:
        """Require a secret only when running in production."""
        if self.environment == "production" and self.app_secret is None:
            raise ValueError("PAM_APP_SECRET is required in production")
        if self.calendar_backend == "google":
            required_values = (
                self.google_client_id,
                self.google_client_secret,
                self.google_redirect_uri,
                self.credential_encryption_key,
            )
            if any(value is None for value in required_values):
                raise ValueError(
                    "Google OAuth configuration is required when "
                    "PAM_CALENDAR_BACKEND=google"
                )
        if self.model_provider == "gemini" and self.gemini_api_key is None:
            raise ValueError("GEMINI_API_KEY is required when model provider is gemini")
        if self.telegram_enabled:
            if self.telegram_bot_token is None:
                raise ValueError(
                    "TELEGRAM_BOT_TOKEN is required when Telegram is enabled"
                )
            if not self.telegram_allowed_user_ids:
                raise ValueError(
                    "TELEGRAM_ALLOWED_USER_IDS is required when Telegram is enabled"
                )
        return self
