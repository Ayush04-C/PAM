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
    model_provider: Literal["fake", "gemini", "bharatcode"] = "fake"
    memory_backend: Literal["disabled", "supermemory"] = "disabled"
    supermemory_api_key: SecretStr | None = None
    supermemory_base_url: str = "https://api.supermemory.ai"
    memory_max_recalled_items: int = 5
    memory_max_content_chars: int = 500
    memory_cli_owner_id: str = "cli-local"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    bharatcode_api_key: SecretStr | None = None
    bharatcode_base_url: str = "https://bharatcode.ai/api/model/v1"
    bharatcode_model: str = "deepseek-v4.1-flash"
    conversation_debug_tool_calls: bool = False
    conversation_max_history_messages: int = 20
    conversation_max_sessions: int = 100
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
        if self.model_provider == "bharatcode" and self.bharatcode_api_key is None:
            raise ValueError(
                "BHARATCODE_API_KEY is required when model provider is bharatcode"
            )
        if self.memory_backend == "supermemory" and self.supermemory_api_key is None:
            raise ValueError(
                "SUPERMEMORY_API_KEY is required when memory backend is supermemory"
            )
        if self.telegram_enabled:
            if self.telegram_bot_token is None:
                raise ValueError(
                    "TELEGRAM_BOT_TOKEN is required when Telegram is enabled"
                )
            if not self.telegram_allowed_user_ids:
                raise ValueError(
                    "TELEGRAM_ALLOWED_USER_IDS is required when Telegram is enabled"
                )
        if not 1 <= self.conversation_max_history_messages <= 100:
            raise ValueError(
                "CONVERSATION_MAX_HISTORY_MESSAGES must be between 1 and 100"
            )
        if not 1 <= self.conversation_max_sessions <= 1_000:
            raise ValueError("CONVERSATION_MAX_SESSIONS must be between 1 and 1000")
        if not 1 <= self.memory_max_recalled_items <= 20:
            raise ValueError("MEMORY_MAX_RECALLED_ITEMS must be between 1 and 20")
        if not 100 <= self.memory_max_content_chars <= 4_000:
            raise ValueError("MEMORY_MAX_CONTENT_CHARS must be between 100 and 4000")
        if not self.memory_cli_owner_id.strip():
            raise ValueError("MEMORY_CLI_OWNER_ID must not be empty")
        return self
