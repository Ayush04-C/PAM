"""Read-only Google Calendar OAuth and CalendarReader integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from pam.domain import CalendarEvent
from pam.security.credentials import CredentialDecryptionError, CredentialStore

GOOGLE_CALENDAR_READONLY_SCOPE = (
    "https://www.googleapis.com/auth/calendar.events.readonly"
)
GOOGLE_CALENDAR_SCOPES = (GOOGLE_CALENDAR_READONLY_SCOPE,)
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleReconnectRequired(RuntimeError):
    """Raised when OAuth consent must be completed again."""


class GoogleCalendarDataError(RuntimeError):
    """Raised when an active Google event cannot be mapped safely."""


@dataclass(frozen=True, slots=True)
class GoogleOAuthConfig:
    """The minimal non-token OAuth client configuration."""

    client_id: str
    client_secret: str
    redirect_uri: str


class GoogleOAuthClient:
    """Create and exchange local OAuth authorization flows."""

    def __init__(self, config: GoogleOAuthConfig) -> None:
        self._config = config

    def authorization_url(self, state: str, code_verifier: str) -> str:
        """Return a Google authorization URL requesting only the read-only scope."""
        flow = self._flow(code_verifier)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return str(url)

    def exchange_code(self, code: str, code_verifier: str) -> str:
        """Exchange an authorization code and return only its refresh token."""
        flow = self._flow(code_verifier)
        flow.fetch_token(code=code)
        refresh_token = flow.credentials.refresh_token
        if not refresh_token:
            raise GoogleReconnectRequired("Google did not provide a refresh credential")
        return str(refresh_token)

    def _flow(self, code_verifier: str) -> Flow:
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": GOOGLE_TOKEN_URI,
                }
            },
            scopes=list(GOOGLE_CALENDAR_SCOPES),
            redirect_uri=self._config.redirect_uri,
            code_verifier=code_verifier,
        )


class GoogleCalendarReader:
    """Read primary-calendar events through the existing CalendarReader contract."""

    def __init__(
        self,
        config: GoogleOAuthConfig,
        credential_store: CredentialStore,
        service_builder: Callable[..., Any] = build,
    ) -> None:
        self._config = config
        self._credential_store = credential_store
        self._service_builder = service_builder

    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        """Read only primary-calendar instances in the inclusive requested range."""
        credentials = self._credentials()
        service = self._service_builder(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )
        range_start = datetime.combine(start_date, time.min, tzinfo=timezone)
        range_end = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=timezone
        )
        events: list[CalendarEvent] = []
        page_token: str | None = None
        while True:
            response = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=range_start.isoformat(),
                    timeMax=range_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute()
            )
            for event in response.get("items", []):
                events.extend(map_google_event(event))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return tuple(events)

    def _credentials(self) -> Credentials:
        try:
            refresh_token = self._credential_store.load()
        except CredentialDecryptionError as error:
            raise GoogleReconnectRequired(
                "Google credentials must be reconnected"
            ) from error
        if refresh_token is None:
            raise GoogleReconnectRequired("Google credentials are not connected")
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
            scopes=list(GOOGLE_CALENDAR_SCOPES),
        )
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise GoogleReconnectRequired(
                "Google credentials must be reconnected"
            ) from error
        return credentials


def map_google_event(event: Mapping[str, Any]) -> tuple[CalendarEvent, ...]:
    """Map one Google response into one or more minimal domain events."""
    if event.get("status") == "cancelled":
        return ()
    title = str(event.get("summary") or "Untitled event")
    start = event.get("start")
    end = event.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        raise GoogleCalendarDataError("Google event is missing start or end")
    if "dateTime" in start and "dateTime" in end:
        return (
            CalendarEvent(
                title=title,
                start=_parse_datetime(start["dateTime"]),
                end=_parse_datetime(end["dateTime"]),
            ),
        )
    if "date" in start and "date" in end:
        start_day = _parse_date(start["date"])
        end_day = _parse_date(end["date"])
        if end_day <= start_day:
            raise GoogleCalendarDataError("Google all-day event has an invalid range")
        return tuple(
            CalendarEvent(title=title, all_day_date=start_day + timedelta(days=offset))
            for offset in range((end_day - start_day).days)
        )
    raise GoogleCalendarDataError("Google event has unsupported time fields")


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise GoogleCalendarDataError("Google event dateTime is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GoogleCalendarDataError("Google event dateTime is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleCalendarDataError("Google event dateTime must include a timezone")
    return parsed


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise GoogleCalendarDataError("Google event date is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise GoogleCalendarDataError("Google event date is invalid") from error
