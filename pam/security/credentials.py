"""Encrypted local storage for the refresh credential used in Phase 4."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken


class CredentialDecryptionError(RuntimeError):
    """Raised when stored credentials cannot be authenticated or decrypted."""


@runtime_checkable
class CredentialStore(Protocol):
    """Store and retrieve the Google refresh token without plaintext persistence."""

    def save(self, refresh_token: str) -> None:
        """Encrypt and persist a refresh token."""

    def load(self) -> str | None:
        """Return the decrypted refresh token, if one is stored."""


class EncryptedFileCredentialStore:
    """Temporary local encrypted credential store until Phase 9 persistence."""

    def __init__(self, path: Path, encryption_key: str) -> None:
        self._path = path
        self._fernet = Fernet(encryption_key.encode("ascii"))

    def save(self, refresh_token: str) -> None:
        """Encrypt the token before writing it to the private local path."""
        encrypted = self._fernet.encrypt(refresh_token.encode("utf-8"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(encrypted)
        with suppress(OSError):
            os.chmod(self._path, 0o600)

    def load(self) -> str | None:
        """Decrypt the stored token only when a calendar read needs it."""
        if not self._path.exists():
            return None
        try:
            return self._fernet.decrypt(self._path.read_bytes()).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise CredentialDecryptionError(
                "stored Google credentials are invalid"
            ) from error
