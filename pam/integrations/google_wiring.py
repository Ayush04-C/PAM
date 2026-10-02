"""Explicit Google-mode application wiring without changing the HTTP contract."""

from __future__ import annotations

from pam.application import AvailabilityService
from pam.config import Settings
from pam.integrations.google_calendar import GoogleCalendarReader, GoogleOAuthConfig
from pam.security.credentials import EncryptedFileCredentialStore


def google_oauth_config(settings: Settings) -> GoogleOAuthConfig:
    """Build Google OAuth configuration after Settings has validated Google mode."""
    assert settings.google_client_id is not None
    assert settings.google_client_secret is not None
    assert settings.google_redirect_uri is not None
    return GoogleOAuthConfig(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        redirect_uri=settings.google_redirect_uri,
    )


def credential_store(settings: Settings) -> EncryptedFileCredentialStore:
    """Create temporary encrypted local credential storage for Google mode."""
    assert settings.credential_encryption_key is not None
    return EncryptedFileCredentialStore(
        settings.credential_storage_path,
        settings.credential_encryption_key.get_secret_value(),
    )


def create_google_availability_service(settings: Settings) -> AvailabilityService:
    """Wire the existing application service to the read-only Google adapter."""
    config = google_oauth_config(settings)
    return AvailabilityService(GoogleCalendarReader(config, credential_store(settings)))
