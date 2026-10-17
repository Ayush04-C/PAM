"""Typed application configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
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
    drive_credential_storage_path: Path = Path(".pam-drive-credentials.bin")
    drive_max_context_chars: int = Field(default=20_000, ge=1, le=20_000)
    drive_enabled: bool = False
    drive_content_enabled: bool = False
    drive_google_client_id: str | None = None
    drive_google_client_secret: SecretStr | None = None
    drive_google_redirect_uri: str = "http://127.0.0.1:8000/oauth/google/drive/callback"
    drive_google_account_email: str | None = None
    drive_owner_id: str | None = None
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
    bharatcode_timeout_seconds: float = Field(default=30.0, ge=5, le=180)
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
        try:
            same_credentials = (
                self.credential_storage_path.resolve()
                == self.drive_credential_storage_path.resolve()
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise ValueError("Credential storage paths must be resolvable") from error
        if same_credentials:
            raise ValueError("Drive and Calendar credential storage paths must differ")
        if self.drive_enabled:
            required = (
                self.drive_google_client_id,
                self.drive_google_client_secret,
                self.drive_google_account_email,
                self.drive_owner_id,
                self.credential_encryption_key,
                self.app_secret,
            )
            if any(value is None or not str(value).strip() for value in required):
                raise ValueError("Drive OAuth and operator configuration is required")
            assert self.app_secret is not None
            if len(self.app_secret.get_secret_value()) < 32:
                raise ValueError(
                    "Drive provisioning requires an APP_SECRET of 32+ characters"
                )
            assert self.drive_google_client_secret is not None
            if not self.drive_google_client_secret.get_secret_value().strip():
                raise ValueError("Drive client secret must not be empty")
            assert self.credential_encryption_key is not None
            try:
                Fernet(
                    self.credential_encryption_key.get_secret_value().encode("ascii")
                )
            except (ValueError, UnicodeError):
                raise ValueError("Drive credential encryption key is invalid") from None
            redirect = urlsplit(self.drive_google_redirect_uri)
            if redirect.port is not None and not 1 <= redirect.port <= 65535:
                raise ValueError("Drive redirect port is invalid")
            if (
                redirect.scheme != "http"
                or redirect.hostname != "127.0.0.1"
                or redirect.path != "/oauth/google/drive/callback"
                or redirect.query
                or redirect.fragment
                or redirect.username
                or redirect.password
            ):
                raise ValueError("Drive redirect must use the local 127.0.0.1 callback")
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
