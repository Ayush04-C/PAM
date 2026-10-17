"""Owner-bound Drive authorization using the existing Google and storage helpers."""

from __future__ import annotations

import json
from functools import partial
from hashlib import sha256
from typing import Literal

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from pam.conversation.models import DriveConsent, DriveConsentRequired
from pam.integrations.google_calendar import (
    GOOGLE_TOKEN_URI,
    GoogleOAuthClient,
    GoogleOAuthConfig,
)
from pam.memory.models import MemoryOwnerId
from pam.security.credentials import EncryptedFileCredentialStore

DRIVE_METADATA_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
DRIVE_SCOPES = (DRIVE_METADATA_SCOPE,)


class DriveAuthorizationError(RuntimeError):
    """A safe, fixed authorization failure suitable for operator responses."""


class DriveGrant(BaseModel):
    """Encrypted persistent grant; tokens and account identifiers stay private."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    owner: str = Field(min_length=1, repr=False)
    account_email: str = Field(min_length=1, repr=False)
    account_id: str = Field(min_length=1, repr=False)
    client_id: str = Field(min_length=1, repr=False)
    scopes: tuple[str, ...]
    refresh_token: SecretStr = Field(repr=False, min_length=1)
    model_destination: str | None = Field(default=None, repr=False)
    allow_read: bool = True
    allow_metadata_transfer: bool = False
    allow_content_transfer: bool = False


class DriveAuthorization:
    """Single operator/account provisioning, independent of Calendar credentials."""

    def __init__(
        self,
        config: GoogleOAuthConfig,
        store: EncryptedFileCredentialStore,
        *,
        owner: MemoryOwnerId,
        account_email: str,
        model_destination: str | None,
    ) -> None:
        self.config = config
        self.store = store
        self.owner = owner
        self.account_email = account_email.strip().casefold()
        self.model_destination = model_destination
        self.oauth = GoogleOAuthClient(
            config, scopes=DRIVE_SCOPES, include_granted_scopes=False
        )

    def load(self) -> DriveGrant:
        """Reject changed owners, clients, accounts or malformed saved grants."""
        raw = self.store.load()
        if raw is None:
            raise DriveAuthorizationError("Drive is not connected. Authorize Drive.")
        try:
            grant = DriveGrant.model_validate_json(raw)
        except ValueError:
            raise DriveAuthorizationError(
                "Drive credentials need reconnecting."
            ) from None
        if (
            grant.owner != self.owner.value
            or grant.client_id != self.config.client_id
            or grant.account_email.casefold() != self.account_email
            or set(grant.scopes) != set(DRIVE_SCOPES)
        ):
            raise DriveAuthorizationError(
                "Drive configuration changed. Reconnect Drive."
            )
        return grant

    def _save(self, grant: DriveGrant) -> None:
        payload = grant.model_dump(mode="json")
        payload["refresh_token"] = grant.refresh_token.get_secret_value()
        self.store.save(json.dumps(payload))

    @staticmethod
    def _account(credentials: Credentials) -> tuple[str, str]:
        with AuthorizedSession(credentials, refresh_timeout=20) as session:
            response = session.get(
                "https://www.googleapis.com/drive/v3/about",
                params={"fields": "user(emailAddress,permissionId)"},
                timeout=20,
            )
            response.raise_for_status()
            user = response.json()["user"]
        email, account_id = user.get("emailAddress"), user.get("permissionId")
        if (
            not isinstance(email, str)
            or not isinstance(account_id, str)
            or not account_id
        ):
            raise DriveAuthorizationError("Google account could not be verified.")
        return email.strip().casefold(), account_id

    def connect(self, code: str, verifier: str) -> None:
        """Validate actual grant and account before replacing any saved credentials."""
        credentials = self.oauth.exchange_credentials(code, verifier)
        scopes = credentials.granted_scopes
        if scopes is None or set(scopes) != set(DRIVE_SCOPES):
            raise DriveAuthorizationError(
                "Google did not grant exactly metadata read access."
            )
        email, account_id = self._account(credentials)
        if email != self.account_email:
            raise DriveAuthorizationError(
                "Wrong Google account. Use the configured account."
            )
        refresh = credentials.refresh_token
        if not refresh:
            previous = self.load()
            if previous.account_id != account_id:
                raise DriveAuthorizationError("Drive account changed. Reconnect Drive.")
            # Prove the old refresh credential still works before retaining it.
            self.check_connection()
            refresh = previous.refresh_token.get_secret_value()
        self._save(
            DriveGrant(
                owner=self.owner.value,
                account_email=email,
                account_id=account_id,
                client_id=self.config.client_id,
                scopes=tuple(scopes),
                refresh_token=SecretStr(refresh),
            )
        )

    def check_connection(self) -> None:
        """Explicit operator-triggered refresh and account check, with no file reads."""
        grant = self.load()
        credentials = self._refresh_credentials(grant)
        if self._account(credentials) != (
            grant.account_email.casefold(),
            grant.account_id,
        ):
            raise DriveAuthorizationError("Drive account changed. Reconnect Drive.")

    def read_credentials(self, owner: MemoryOwnerId) -> Credentials:
        """Check the current owner and saved read consent before any network I/O."""
        if owner != self.owner:
            raise DriveConsentRequired("Drive read consent is required.")
        grant = self.load()
        if grant.allow_read is not True:
            raise DriveConsentRequired("Drive read consent is required.")
        return self._refresh_credentials(grant)

    def _refresh_credentials(self, grant: DriveGrant) -> Credentials:
        """Share scoped, bounded refresh between provisioning and metadata reads."""
        credentials = Credentials(
            token=None,
            refresh_token=grant.refresh_token.get_secret_value(),
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=list(DRIVE_SCOPES),
        )
        try:
            credentials.refresh(partial(Request(), timeout=20))
        except RefreshError as error:
            if error.retryable:
                raise RuntimeError("Drive refresh temporarily unavailable") from error
            raise DriveAuthorizationError(
                "Drive authorization expired. Reconnect Drive."
            ) from error
        if credentials.granted_scopes is not None and set(
            credentials.granted_scopes
        ) != set(DRIVE_SCOPES):
            raise DriveAuthorizationError("Drive permissions changed. Reconnect Drive.")
        return credentials

    def set_permissions(
        self,
        *,
        allow_read: bool,
        allow_metadata_transfer: bool,
        confirmed_destination: str | None,
    ) -> None:
        """Operator consent is separate from Google OAuth; content stays disabled."""
        grant = self.load()
        if allow_metadata_transfer and (
            not allow_read
            or not self.model_destination
            or confirmed_destination != self.model_destination
        ):
            raise DriveAuthorizationError(
                "Review and confirm the current model destination."
            )
        self._save(
            grant.model_copy(
                update={
                    "allow_read": allow_read,
                    "allow_metadata_transfer": allow_read and allow_metadata_transfer,
                    "allow_content_transfer": False,
                    "model_destination": self.model_destination
                    if allow_metadata_transfer
                    else None,
                }
            )
        )

    def consent(self, owner: MemoryOwnerId) -> DriveConsent:
        """Trusted future composition loads current permissions for every request."""
        grant = self.load()
        if owner != self.owner:
            raise DriveAuthorizationError("Drive owner does not match.")
        matches = grant.model_destination == self.model_destination
        return DriveConsent(
            owner,
            self.model_destination or "",
            grant.allow_read,
            matches and grant.allow_metadata_transfer,
            False,
            sha256(
                json.dumps(
                    [
                        grant.account_id,
                        grant.client_id,
                        grant.refresh_token.get_secret_value(),
                        sorted(grant.scopes),
                    ]
                ).encode()
            ).hexdigest(),
        )

    def disconnect(self) -> None:
        """Remove only the local Drive grant; remote Google revocation is separate."""
        self.store.delete()
