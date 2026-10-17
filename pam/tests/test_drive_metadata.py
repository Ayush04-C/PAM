"""Offline Stage 5 bounded-read, validation, and consent regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from google.auth.exceptions import RefreshError
from pydantic import SecretStr

from pam.integrations import drive_auth, google_drive
from pam.integrations.drive_auth import DRIVE_SCOPES, DriveAuthorization, DriveGrant
from pam.integrations.google_calendar import GoogleOAuthConfig
from pam.integrations.google_drive import DriveReadError, GoogleDriveReader
from pam.integrations.google_wiring import create_drive_authorization
from pam.memory.models import MemoryOwnerId
from pam.security.credentials import EncryptedFileCredentialStore
from pam.tests.test_drive_oauth import enabled_settings

OWNER = MemoryOwnerId("cli-local")
FILE = {
    "id": "test-file_1",
    "name": "Private test document",
    "mimeType": "text/plain",
    "modifiedTime": "2026-10-17T12:00:00Z",
    "trashed": False,
}


class Response:
    def __init__(self, payload, status=200, raw=None):
        self.payload = payload
        self.status_code = status
        self.raw = json.dumps(payload).encode() if raw is None else raw
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.raw), chunk_size):
            yield self.raw[offset : offset + chunk_size]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    auth = DriveAuthorization(
        GoogleOAuthConfig(
            "drive-client",
            "private-client-secret",
            "http://127.0.0.1:8000/oauth/google/drive/callback",
        ),
        EncryptedFileCredentialStore(
            tmp_path / "drive.bin", Fernet.generate_key().decode()
        ),
        owner=OWNER,
        account_email="owner@example.test",
        model_destination="test-model",
    )
    auth._save(
        DriveGrant(
            owner=OWNER.value,
            account_email="owner@example.test",
            account_id="id",
            client_id="drive-client",
            scopes=DRIVE_SCOPES,
            refresh_token=SecretStr("PRIVATE-TOKEN"),
        )
    )
    state = SimpleNamespace(
        auth=auth,
        calls=[],
        refreshes=[],
        response=Response({"files": [FILE]}),
        error=None,
        refresh_error=None,
    )

    class Credentials:
        granted_scopes = DRIVE_SCOPES

        def __init__(self, **kwargs):
            state.refreshes.append(kwargs)

        def refresh(self, request):
            assert request.keywords["timeout"] == 20
            if state.refresh_error:
                raise state.refresh_error

    class Session:
        def __init__(self, credentials, **kwargs):
            assert kwargs["max_refresh_attempts"] == 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            state.calls.append((url, kwargs))
            if state.error:
                raise state.error
            return state.response

    monkeypatch.setattr(drive_auth, "Credentials", Credentials)
    monkeypatch.setattr(google_drive, "AuthorizedSession", Session)
    state.reader = GoogleDriveReader(auth)
    return state


def test_search_escapes_query_bounds_fields_and_returns_untrusted_metadata(harness):
    page = harness.reader.search(OWNER, name="Bob's \\ notes")
    assert len(page.files) == 1
    assert page.files[0].file_id == FILE["id"]
    assert page.files[0].modified_time.tzinfo is not None
    assert (
        page.files[0].source_url == "https://drive.google.com/file/d/test-file_1/view"
    )
    url, request = harness.calls[0]
    assert url == "https://www.googleapis.com/drive/v3/files"
    assert request["params"] == {
        "q": "trashed = false and name contains 'Bob\\'s \\\\ notes'",
        "pageSize": 10,
        "corpora": "user",
        "spaces": "drive",
        "includeItemsFromAllDrives": "false",
        "supportsAllDrives": "false",
        "orderBy": "modifiedTime desc,name",
        "fields": (
            "nextPageToken,incompleteSearch,"
            "files(id,name,mimeType,modifiedTime,trashed,driveId)"
        ),
    }
    assert request["timeout"] == 20 and request["stream"] is True
    assert request["allow_redirects"] is False
    assert harness.response.closed
    assert harness.refreshes[0]["scopes"] == list(DRIVE_SCOPES)
    assert FILE["name"] not in repr(page) + repr(page.files[0])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": " "},
        {"name": "x" * 201},
        {"name": "bad\nquery"},
        {"name": 42},
        {"page_size": 0},
        {"page_size": 51},
        {"page_size": True},
        {"page_size": "10"},
        {"page_token": ""},
        {"page_token": "x" * 4097},
        {"page_token": "bad token"},
        {"page_token": 42},
    ],
)
def test_invalid_search_never_loads_network_credentials(harness, kwargs):
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER, **kwargs)
    assert error.value.code == "invalid_request"
    assert harness.calls == harness.refreshes == []


@pytest.mark.parametrize(
    "identifier", ["", "../secret", "https://evil.test", "x" * 257, 42]
)
def test_invalid_id_never_reaches_google(harness, identifier):
    with pytest.raises(DriveReadError) as error:
        harness.reader.get_metadata(OWNER, identifier)
    assert error.value.code == "invalid_request"
    assert harness.calls == harness.refreshes == []


@pytest.mark.parametrize("operation", ["search", "get"])
def test_owner_mismatch_and_withdrawn_consent_prevent_all_google_calls(
    harness, operation
):
    def call(owner):
        if operation == "search":
            return harness.reader.search(owner)
        return harness.reader.get_metadata(owner, FILE["id"])

    with pytest.raises(DriveReadError) as error:
        call(MemoryOwnerId("another-owner"))
    assert error.value.code == "consent_required"
    harness.auth.set_permissions(
        allow_read=False, allow_metadata_transfer=False, confirmed_destination=None
    )
    with pytest.raises(DriveReadError) as error:
        call(OWNER)
    assert error.value.code == "consent_required"
    assert harness.calls == harness.refreshes == []


def test_consent_is_reloaded_between_pages(harness):
    harness.reader.search(OWNER)
    harness.auth.set_permissions(
        allow_read=False, allow_metadata_transfer=False, confirmed_destination=None
    )
    with pytest.raises(DriveReadError):
        harness.reader.search(OWNER, page_token="next-token")
    assert len(harness.calls) == len(harness.refreshes) == 1


@pytest.mark.parametrize(
    "failure", ["missing", "corrupt", "client", "account", "wrong-key"]
)
def test_bad_grant_requires_reconnect_without_network(harness, failure):
    if failure == "missing":
        harness.auth.disconnect()
    elif failure == "corrupt":
        harness.auth.store.save("bad-json")
    elif failure == "client":
        harness.auth.config = replace(harness.auth.config, client_id="changed")
    elif failure == "account":
        harness.auth.account_email = "changed@example.test"
    else:
        harness.auth.store = EncryptedFileCredentialStore(
            harness.auth.store._path, Fernet.generate_key().decode()
        )
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER)
    assert error.value.code == "reconnect_required"
    assert harness.calls == harness.refreshes == []


def test_empty_partial_page_preserves_continuation_without_auto_scan(harness):
    harness.response = Response(
        {"files": [], "nextPageToken": "next-token", "incompleteSearch": True}
    )
    page = harness.reader.search(OWNER, page_size=50, page_token="previous-token")
    assert page.files == () and page.next_page_token == "next-token"
    assert page.incomplete_search
    assert len(harness.calls) == 1
    assert harness.calls[0][1]["params"]["pageToken"] == "previous-token"


def test_get_metadata_uses_exact_id_and_never_downloads(harness):
    harness.response = Response(FILE)
    result = harness.reader.get_metadata(OWNER, FILE["id"])
    assert result.name == FILE["name"]
    assert harness.calls[0][0].endswith("/files/test-file_1")
    assert harness.calls[0][1]["params"] == {
        "fields": "id,name,mimeType,modifiedTime,trashed,driveId",
        "supportsAllDrives": "false",
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "id": "folder",
            "name": "Folder",
            "mimeType": "application/vnd.google-apps.folder",
        },
        {
            "id": "shortcut",
            "name": "Shortcut",
            "mimeType": "application/vnd.google-apps.shortcut",
        },
    ],
)
def test_folders_and_shortcuts_are_metadata_only(harness, metadata):
    harness.response = Response(metadata)
    result = harness.reader.get_metadata(OWNER, metadata["id"])
    assert result.modified_time is None
    assert result.source_url.startswith("https://drive.google.com/")
    assert len(harness.calls) == 1


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"name": None}, "invalid_response"),
        ({"name": "x" * 1025}, "invalid_response"),
        ({"id": "different-id"}, "invalid_response"),
        ({"mimeType": "bad mime"}, "invalid_response"),
        ({"modifiedTime": "yesterday"}, "invalid_response"),
        ({"modifiedTime": "2026-10-17T12:00:00"}, "invalid_response"),
        ({"trashed": True}, "unavailable"),
        ({"driveId": "shared-drive"}, "unavailable"),
    ],
)
def test_invalid_or_out_of_scope_file_metadata_is_rejected(harness, patch, code):
    harness.response = Response(FILE | patch)
    with pytest.raises(DriveReadError) as error:
        harness.reader.get_metadata(OWNER, FILE["id"])
    assert error.value.code == code


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"files": None},
        {"files": [None]},
        {"files": [FILE] * 11},
        {"nextPageToken": 42},
        {"incompleteSearch": "true"},
    ],
)
def test_malformed_pages_fail_safely(harness, payload):
    harness.response = Response(payload)
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER)
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize(
    "raw",
    [b"not-json", b"\xff", b"x" * (128 * 1024 + 1)],
    ids=["invalid-json", "invalid-utf8", "oversized-body"],
)
def test_invalid_or_oversized_bodies_are_closed_and_rejected(harness, raw):
    harness.response = Response(None, raw=raw)
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER)
    assert error.value.code == "invalid_response"
    assert harness.response.closed


@pytest.mark.parametrize(
    "status,reason,code,retryable",
    [
        (400, None, "invalid_request", False),
        (401, None, "reconnect_required", False),
        (403, None, "unavailable", False),
        (404, None, "unavailable", False),
        (429, None, "rate_limited", True),
        (503, None, "temporary_failure", True),
        (403, "userRateLimitExceeded", "rate_limited", True),
        (302, None, "temporary_failure", True),
    ],
)
def test_http_errors_are_classified_without_payload_leakage(
    harness, caplog, status, reason, code, retryable
):
    harness.response = Response(
        {"error": {"message": "PRIVATE-TOKEN", "errors": [{"reason": reason}]}}, status
    )
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER, name="PRIVATE-SEARCH")
    assert error.value.code == code and error.value.retryable == retryable
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert len(harness.calls) == 1


def test_rejected_pagination_requires_search_restart(harness):
    harness.response = Response({}, 400)
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER, page_token="expired")
    assert error.value.code == "invalid_page_token"


@pytest.mark.parametrize("retryable", [True, False])
def test_refresh_failure_prevents_file_reads(harness, retryable):
    harness.refresh_error = RefreshError("PRIVATE-TOKEN", retryable=retryable)
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER)
    assert error.value.code == (
        "temporary_failure" if retryable else "reconnect_required"
    )
    assert harness.calls == []


def test_network_timeout_is_safe_and_not_retried(harness):
    harness.error = TimeoutError("PRIVATE-URL")
    with pytest.raises(DriveReadError) as error:
        harness.reader.search(OWNER)
    assert error.value.retryable and "PRIVATE" not in str(error.value)
    assert len(harness.calls) == 1


def test_factory_reuses_validated_configuration_without_reading_credentials(tmp_path):
    settings = enabled_settings(drive_credential_storage_path=tmp_path / "missing.bin")
    auth = create_drive_authorization(settings)
    assert auth.owner == OWNER and auth.store.load() is None
    assert auth.config.client_id == settings.drive_google_client_id
