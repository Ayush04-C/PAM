"""Explicit Google-mode application wiring without changing the HTTP contract."""

from __future__ import annotations

from pam.application import AvailabilityService
from pam.config import Settings
from pam.conversation.factory import configured_model_destination
from pam.integrations.drive_auth import DriveAuthorization
from pam.integrations.google_calendar import GoogleCalendarReader, GoogleOAuthConfig
from pam.memory.models import MemoryOwnerId
from pam.security.credentials import EncryptedFileCredentialStore


def create_drive_authorization(settings: Settings) -> DriveAuthorization:
    """Reuse the same owner-bound grant configuration for HTTP and local reads."""
    if not settings.drive_enabled:
        raise ValueError("Drive is disabled")
    assert settings.drive_google_client_id is not None
    assert settings.drive_google_client_secret is not None
    assert settings.drive_google_account_email is not None
    assert settings.drive_owner_id is not None
    assert settings.credential_encryption_key is not None
    return DriveAuthorization(
        GoogleOAuthConfig(
            settings.drive_google_client_id,
            settings.drive_google_client_secret.get_secret_value(),
            settings.drive_google_redirect_uri,
        ),
        EncryptedFileCredentialStore(
            settings.drive_credential_storage_path,
            settings.credential_encryption_key.get_secret_value(),
        ),
        owner=MemoryOwnerId(settings.drive_owner_id),
        account_email=settings.drive_google_account_email,
        model_destination=configured_model_destination(settings),
    )


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
