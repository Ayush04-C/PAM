"""Offline tests for Phase 4 read-only Google Calendar integration."""

from __future__ import annotations

from datetime import date

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pam.api.google_oauth import InMemoryOAuthStateStore, create_google_oauth_router
from pam.application import AvailabilityService, CalendarUnavailable
from pam.domain import DISPLAY_TIMEZONE
from pam.integrations.google_calendar import (
    GOOGLE_CALENDAR_READONLY_SCOPE,
    GOOGLE_CALENDAR_SCOPES,
    GoogleCalendarDataError,
    GoogleCalendarReader,
    GoogleOAuthConfig,
    GoogleReconnectRequired,
    map_google_event,
)
from pam.security.credentials import (
    CredentialDecryptionError,
    EncryptedFileCredentialStore,
)


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def save(self, refresh_token: str) -> None:
        self.value = refresh_token

    def load(self) -> str | None:
        return self.value


class FakeOAuthClient:
    def __init__(self) -> None:
        self.state: str | None = None
        self.code: str | None = None
        self.code_verifier: str | None = None

    def authorization_url(self, state: str, code_verifier: str) -> str:
        self.state = state
        self.code_verifier = code_verifier
        return f"https://accounts.example.test/authorize?state={state}"

    def exchange_code(self, code: str, code_verifier: str) -> str:
        self.code = code
        assert code_verifier == self.code_verifier
        return "REFRESH_TOKEN_DO_NOT_LOG"


class FakeEventsResource:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def list(self, **kwargs: object) -> FakeEventsResource:
        self.calls.append(kwargs)
        return self

    def execute(self) -> dict[str, object]:
        return self.pages.pop(0)


class FakeCalendarService:
    def __init__(self, events: FakeEventsResource) -> None:
        self.events_resource = events

    def events(self) -> FakeEventsResource:
        return self.events_resource


class FailingEventsResource:
    def list(self, **kwargs: object) -> FailingEventsResource:
        return self

    def execute(self) -> dict[str, object]:
        raise RuntimeError("calendar API unavailable")


class RefreshingCredentials:
    refresh_calls = 0

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def refresh(self, request: object) -> None:
        type(self).refresh_calls += 1


class RevokedCredentials(RefreshingCredentials):
    def refresh(self, request: object) -> None:
        from google.auth.exceptions import RefreshError

        raise RefreshError("revoked")


def google_config() -> GoogleOAuthConfig:
    return GoogleOAuthConfig(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://127.0.0.1/callback",
    )


def test_google_scope_is_exactly_the_narrow_read_only_events_scope() -> None:
    assert GOOGLE_CALENDAR_SCOPES == (GOOGLE_CALENDAR_READONLY_SCOPE,)
    assert GOOGLE_CALENDAR_READONLY_SCOPE == (
        "https://www.googleapis.com/auth/calendar.events.readonly"
    )


def test_encrypted_file_store_round_trips_without_plaintext(tmp_path) -> None:
    path = tmp_path / "credentials.bin"
    token = "REFRESH_TOKEN_DO_NOT_LOG"
    store = EncryptedFileCredentialStore(path, Fernet.generate_key().decode())

    store.save(token)

    assert store.load() == token
    assert token.encode() not in path.read_bytes()


def test_wrong_encryption_key_and_missing_store_are_deterministic(tmp_path) -> None:
    path = tmp_path / "credentials.bin"
    first = EncryptedFileCredentialStore(path, Fernet.generate_key().decode())
    first.save("REFRESH_TOKEN_DO_NOT_LOG")

    wrong_key_store = EncryptedFileCredentialStore(path, Fernet.generate_key().decode())
    missing_store = EncryptedFileCredentialStore(
        tmp_path / "missing.bin", Fernet.generate_key().decode()
    )

    with pytest.raises(CredentialDecryptionError):
        wrong_key_store.load()
    assert missing_store.load() is None


def test_oauth_start_and_callback_use_one_time_state_and_safe_response() -> None:
    oauth_client = FakeOAuthClient()
    credential_store = MemoryCredentialStore()
    app = FastAPI()
    app.include_router(
        create_google_oauth_router(
            oauth_client, InMemoryOAuthStateStore(), credential_store
        )
    )
    client = TestClient(app)

    start = client.get("/oauth/google/start", follow_redirects=False)
    assert start.status_code == 307
    assert oauth_client.state
    assert oauth_client.code_verifier
    assert 43 <= len(oauth_client.code_verifier) <= 128
    assert "REFRESH_TOKEN_DO_NOT_LOG" not in start.text

    missing = client.get("/oauth/google/callback?code=code")
    mismatch = client.get("/oauth/google/callback?state=wrong&code=code")
    callback = client.get(
        f"/oauth/google/callback?state={oauth_client.state}&code=code"
    )
    replay = client.get(f"/oauth/google/callback?state={oauth_client.state}&code=code")

    assert missing.status_code == 400
    assert mismatch.status_code == 400
    assert callback.json() == {"status": "connected"}
    assert replay.status_code == 400
    assert credential_store.value == "REFRESH_TOKEN_DO_NOT_LOG"
    assert "REFRESH_TOKEN_DO_NOT_LOG" not in callback.text


def test_google_reader_uses_primary_exact_range_recurrence_and_pagination() -> None:
    pages: list[dict[str, object]] = [
        {
            "items": [
                {
                    "summary": "First recurring instance",
                    "start": {"dateTime": "2026-09-28T10:00:00+05:30"},
                    "end": {"dateTime": "2026-09-28T11:00:00+05:30"},
                }
            ],
            "nextPageToken": "page-2",
        },
        {
            "items": [
                {
                    "summary": "Second recurring instance",
                    "start": {"dateTime": "2026-09-29T10:00:00+05:30"},
                    "end": {"dateTime": "2026-09-29T11:00:00+05:30"},
                }
            ]
        },
    ]
    events_resource = FakeEventsResource(pages)
    reader = GoogleCalendarReader(
        google_config(),
        MemoryCredentialStore(),
        lambda *_args, **_kwargs: FakeCalendarService(events_resource),
    )
    reader._credentials = lambda: object()  # type: ignore[method-assign]

    events = reader.read_events(date(2026, 9, 28), date(2026, 10, 4), DISPLAY_TIMEZONE)

    assert [event.title for event in events] == [
        "First recurring instance",
        "Second recurring instance",
    ]
    first, second = events_resource.calls
    assert first["calendarId"] == "primary"
    assert first["timeMin"] == "2026-09-28T00:00:00+05:30"
    assert first["timeMax"] == "2026-10-05T00:00:00+05:30"
    assert first["singleEvents"] is True
    assert first["orderBy"] == "startTime"
    assert first["pageToken"] is None
    assert second["pageToken"] == "page-2"


def test_google_event_mapping_handles_all_day_cancelled_and_malformed_events() -> None:
    all_day = map_google_event(
        {
            "summary": "Conference",
            "start": {"date": "2026-09-28"},
            "end": {"date": "2026-09-30"},
        }
    )

    assert [event.all_day_date for event in all_day] == [
        date(2026, 9, 28),
        date(2026, 9, 29),
    ]
    assert map_google_event({"status": "cancelled"}) == ()
    with pytest.raises(GoogleCalendarDataError):
        map_google_event({"summary": "Broken", "start": {}, "end": {}})


def test_missing_google_credentials_require_reconnect_and_no_write_public_api() -> None:
    reader = GoogleCalendarReader(google_config(), MemoryCredentialStore())

    with pytest.raises(GoogleReconnectRequired):
        reader.read_events(date(2026, 9, 28), date(2026, 9, 28), DISPLAY_TIMEZONE)
    assert not {"create", "update", "delete", "insert", "patch"} & set(dir(reader))


def test_expired_credential_refreshes_before_the_calendar_read(monkeypatch) -> None:
    from pam.integrations import google_calendar

    RefreshingCredentials.refresh_calls = 0
    monkeypatch.setattr(google_calendar, "Credentials", RefreshingCredentials)
    reader = GoogleCalendarReader(
        google_config(),
        _connected_store(),
        lambda *_args, **_kwargs: FakeCalendarService(
            FakeEventsResource([{"items": []}])
        ),
    )

    assert (
        reader.read_events(date(2026, 9, 28), date(2026, 9, 28), DISPLAY_TIMEZONE) == ()
    )
    assert RefreshingCredentials.refresh_calls == 1


def test_revoked_credential_requires_reconnect(monkeypatch) -> None:
    from pam.integrations import google_calendar

    monkeypatch.setattr(google_calendar, "Credentials", RevokedCredentials)
    reader = GoogleCalendarReader(google_config(), _connected_store())

    with pytest.raises(GoogleReconnectRequired):
        reader.read_events(date(2026, 9, 28), date(2026, 9, 28), DISPLAY_TIMEZONE)


def test_calendar_api_failure_maps_to_existing_calendar_unavailable(
    monkeypatch,
) -> None:
    from pam.integrations import google_calendar

    monkeypatch.setattr(google_calendar, "Credentials", RefreshingCredentials)
    reader = GoogleCalendarReader(
        google_config(),
        _connected_store(),
        lambda *_args, **_kwargs: FakeCalendarService(FailingEventsResource()),
    )

    with pytest.raises(CalendarUnavailable):
        AvailabilityService(reader).get_weekly_availability(
            date(2026, 9, 28), date(2026, 9, 28), DISPLAY_TIMEZONE
        )


def _connected_store() -> MemoryCredentialStore:
    store = MemoryCredentialStore()
    store.save("REFRESH_TOKEN_DO_NOT_LOG")
    return store
