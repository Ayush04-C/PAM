"""Bounded metadata-only Drive reads, independent of MCP and model execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any

from google.auth.transport.requests import AuthorizedSession, Request

from pam.conversation.models import DriveConsentRequired
from pam.integrations.drive_auth import DriveAuthorization, DriveAuthorizationError
from pam.memory.models import MemoryOwnerId
from pam.security.credentials import CredentialDecryptionError

_ROOT = "https://www.googleapis.com/drive/v3/files"
_FIELDS = "id,name,mimeType,modifiedTime,trashed,driveId"
_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_MIME = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
_MAX_RESPONSE_BYTES = 128 * 1024
_ERRORS = {
    "invalid_request": "Invalid Drive request. Check the search or file identifier.",
    "consent_required": "Drive read consent is required for this owner.",
    "reconnect_required": "Drive authorization needs reconnecting.",
    "unavailable": "The Drive file or operation is unavailable to this account.",
    "invalid_page_token": "Drive pagination expired or is invalid. Restart the search.",
    "rate_limited": "Drive rate limit reached. Please retry later.",
    "temporary_failure": "Drive is temporarily unavailable. Please retry later.",
    "invalid_response": "Drive returned invalid or oversized metadata.",
}


class DriveReadError(RuntimeError):
    """Fixed, payload-free errors for future MCP translation."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.retryable = code in {"rate_limited", "temporary_failure"}
        super().__init__(_ERRORS[code])


@dataclass(frozen=True, slots=True)
class DriveFile:
    """Validated metadata remains untrusted and hidden from default repr/logs."""

    file_id: str = field(repr=False)
    name: str = field(repr=False)
    mime_type: str
    modified_time: datetime | None
    source_url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DrivePage:
    files: tuple[DriveFile, ...] = field(repr=False)
    next_page_token: str | None = field(default=None, repr=False)
    incomplete_search: bool = False


def _valid_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 4096
        and all(33 <= ord(char) <= 126 for char in value)
    )


def _metadata(value: object) -> DriveFile:
    if not isinstance(value, dict):
        raise DriveReadError("invalid_response")
    identifier, name, mime = value.get("id"), value.get("name"), value.get("mimeType")
    if (
        not isinstance(identifier, str)
        or not _ID.fullmatch(identifier)
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 1024
        or not isinstance(mime, str)
        or len(mime) > 255
        or not _MIME.fullmatch(mime)
    ):
        raise DriveReadError("invalid_response")
    if value.get("trashed", False) is not False or value.get("driveId"):
        raise DriveReadError("unavailable")
    modified = value.get("modifiedTime")
    timestamp = None
    if modified is not None:
        try:
            if not isinstance(modified, str) or len(modified) > 64:
                raise ValueError
            timestamp = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
        except ValueError:
            raise DriveReadError("invalid_response") from None
    location = (
        "drive/folders" if mime == "application/vnd.google-apps.folder" else "file/d"
    )
    suffix = "" if location == "drive/folders" else "/view"
    return DriveFile(
        identifier,
        name,
        mime,
        timestamp,
        f"https://drive.google.com/{location}/{identifier}{suffix}",
    )


class GoogleDriveReader:
    """One page per call; no content, writes, arbitrary URLs or durable memory."""

    def __init__(self, authorization: DriveAuthorization) -> None:
        self._authorization = authorization

    @property
    def owner(self) -> MemoryOwnerId:
        """Expose trusted configured identity for private single-owner composition."""
        return self._authorization.owner

    def search(
        self,
        owner: MemoryOwnerId,
        *,
        name: str | None = None,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> DrivePage:
        if (
            type(page_size) is not int
            or not 1 <= page_size <= 50
            or (page_token is not None and not _valid_token(page_token))
            or (
                name is not None
                and (
                    not isinstance(name, str)
                    or not name.strip()
                    or len(name) > 200
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)
                )
            )
        ):
            raise DriveReadError("invalid_request")
        query = "trashed = false"
        if name is not None:
            escaped = name.strip().replace("\\", "\\\\").replace("'", "\\'")
            query += f" and name contains '{escaped}'"
        params: dict[str, str | int] = {
            "q": query,
            "pageSize": page_size,
            "corpora": "user",
            "spaces": "drive",
            "includeItemsFromAllDrives": "false",
            "supportsAllDrives": "false",
            "orderBy": "modifiedTime desc,name",
            "fields": f"nextPageToken,incompleteSearch,files({_FIELDS})",
        }
        if page_token is not None:
            params["pageToken"] = page_token
        payload = self._request(owner, _ROOT, params, paginated=page_token is not None)
        files = payload.get("files", [])
        token = payload.get("nextPageToken")
        incomplete = payload.get("incompleteSearch", False)
        if (
            not isinstance(files, list)
            or len(files) > page_size
            or (token is not None and not _valid_token(token))
            or type(incomplete) is not bool
        ):
            raise DriveReadError("invalid_response")
        return DrivePage(tuple(_metadata(item) for item in files), token, incomplete)

    def get_metadata(self, owner: MemoryOwnerId, file_id: str) -> DriveFile:
        if not isinstance(file_id, str) or not _ID.fullmatch(file_id):
            raise DriveReadError("invalid_request")
        result = _metadata(
            self._request(
                owner,
                f"{_ROOT}/{file_id}",
                {"fields": _FIELDS, "supportsAllDrives": "false"},
            )
        )
        if result.file_id != file_id:
            raise DriveReadError("invalid_response")
        return result

    def _request(
        self,
        owner: MemoryOwnerId,
        url: str,
        params: dict[str, str | int],
        *,
        paginated: bool = False,
    ) -> dict[str, Any]:
        try:
            credentials = self._authorization.read_credentials(owner)
            # Refresh was checked above. Do not retry a 401 with an implicit grant.
            with (
                AuthorizedSession(
                    credentials,
                    max_refresh_attempts=0,
                    auth_request=partial(Request(), timeout=20),
                ) as session,
                session.get(
                    url, params=params, timeout=20, stream=True, allow_redirects=False
                ) as response,
            ):
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    raw.extend(chunk)
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise DriveReadError("invalid_response")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    payload = None
                status = response.status_code
                if status != 200:
                    self._http_error(status, payload, paginated)
                if not isinstance(payload, dict):
                    raise DriveReadError("invalid_response")
                return payload
        except DriveReadError:
            raise
        except DriveConsentRequired:
            raise DriveReadError("consent_required") from None
        except (DriveAuthorizationError, CredentialDecryptionError):
            raise DriveReadError("reconnect_required") from None
        except Exception:
            raise DriveReadError("temporary_failure") from None

    @staticmethod
    def _http_error(status: int, payload: object, paginated: bool) -> None:
        if status == 401:
            raise DriveReadError("reconnect_required")
        if status == 400:
            raise DriveReadError(
                "invalid_page_token" if paginated else "invalid_request"
            )
        if status == 429:
            raise DriveReadError("rate_limited")
        if status == 403:
            error = payload.get("error") if isinstance(payload, dict) else None
            details = error.get("errors", []) if isinstance(error, dict) else []
            if isinstance(details, list) and any(
                isinstance(item, dict)
                and item.get("reason")
                in {
                    "rateLimitExceeded",
                    "userRateLimitExceeded",
                    "dailyLimitExceeded",
                }
                for item in details
            ):
                raise DriveReadError("rate_limited")
        if status in {403, 404, 410}:
            raise DriveReadError("unavailable")
        raise DriveReadError("temporary_failure")
