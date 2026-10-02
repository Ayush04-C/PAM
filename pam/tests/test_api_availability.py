"""Integration tests for PAM's internal availability HTTP API."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from pam.api.audit import InMemoryAuditSink
from pam.application import AvailabilityService
from pam.application.local_calendar import create_local_availability_service
from pam.config import Settings
from pam.domain import DISPLAY_TIMEZONE, CalendarEvent
from pam.main import REQUEST_ID_HEADER, create_app

REQUEST_BODY = {
    "start_date": "2026-09-28",
    "end_date": "2026-10-04",
    "timezone": "Asia/Kolkata",
}


class FailingReader:
    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        raise RuntimeError("private calendar backend failure")


class ConfidentialReader:
    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        return (
            CalendarEvent(
                "CONFIDENTIAL_PRIVATE_MEETING_XYZ",
                start=date_to_datetime(start_date, 10),
                end=date_to_datetime(start_date, 11),
            ),
        )


class LogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def date_to_datetime(day: date, hour: int):
    return datetime(day.year, day.month, day.day, hour, tzinfo=DISPLAY_TIMEZONE)


def test_health_remains_available() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_availability_full_path_matches_real_application_service() -> None:
    service = create_local_availability_service()
    response = TestClient(create_app(service)).post("/availability", json=REQUEST_BODY)

    expected = service.get_weekly_availability(
        date(2026, 9, 28), date(2026, 10, 4), DISPLAY_TIMEZONE
    )
    assert response.status_code == 200
    assert response.json() == {"availability": expected}


@pytest.mark.parametrize(
    "body",
    [
        {**REQUEST_BODY, "start_date": "not-a-date"},
        {**REQUEST_BODY, "end_date": "not-a-date"},
        {"start_date": "2026-09-28", "end_date": "2026-10-04"},
    ],
    ids=["malformed-start", "malformed-end", "missing-timezone"],
)
def test_malformed_request_is_rejected_safely(body: dict[str, str]) -> None:
    response = TestClient(create_app()).post("/availability", json=body)

    assert response.status_code == 422
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {**REQUEST_BODY, "start_date": "2026-10-10", "end_date": "2026-10-01"},
        {**REQUEST_BODY, "end_date": "2026-11-01"},
        {**REQUEST_BODY, "timezone": "UTC"},
        {**REQUEST_BODY, "timezone": "unknown/timezone"},
    ],
    ids=["reversed", "too-long", "unsupported", "malformed-timezone"],
)
def test_application_validation_maps_to_safe_client_errors(
    body: dict[str, str],
) -> None:
    response = TestClient(create_app()).post("/availability", json=body)

    assert response.status_code == 400
    assert "Traceback" not in response.text


def test_unavailable_calendar_maps_to_safe_503_with_request_id() -> None:
    app = create_app(AvailabilityService(FailingReader()))
    response = TestClient(app).post("/availability", json=REQUEST_BODY)

    assert response.status_code == 503
    assert response.json() == {"detail": "calendar is unavailable"}
    assert response.headers[REQUEST_ID_HEADER]
    assert "private calendar backend failure" not in response.text


def test_availability_preserves_incoming_request_id_and_records_safe_audit() -> None:
    audit_sink = InMemoryAuditSink()
    response = TestClient(
        create_app(
            audit_sink=audit_sink,
            settings=Settings(_env_file=None, model_provider="fake"),
        )
    ).post(
        "/availability", json=REQUEST_BODY, headers={REQUEST_ID_HEADER: "api-request"}
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "api-request"
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].request_id == "api-request"
    assert asdict(audit_sink.events[0]) == {
        "operation": "get_weekly_availability",
        "request_id": "api-request",
        "outcome": "success",
        "start_date": date(2026, 9, 28),
        "end_date": date(2026, 10, 4),
        "timezone": "Asia/Kolkata",
    }


def test_logs_and_audit_never_capture_event_titles_or_secrets() -> None:
    audit_sink = InMemoryAuditSink()
    logger = logging.getLogger("pam")
    collector = LogCollector()
    logger.addHandler(collector)
    try:
        response = TestClient(
            create_app(AvailabilityService(ConfidentialReader()), audit_sink)
        ).post(
            "/availability",
            json=REQUEST_BODY,
            headers={"X-API-Key": "top-secret-value"},
        )
    finally:
        logger.removeHandler(collector)

    stored_audit = str([asdict(event) for event in audit_sink.events])
    captured_logs = "\n".join(collector.messages)
    assert response.status_code == 200
    assert "CONFIDENTIAL_PRIVATE_MEETING_XYZ" not in stored_audit
    assert "CONFIDENTIAL_PRIVATE_MEETING_XYZ" not in captured_logs
    assert "top-secret-value" not in stored_audit
    assert "top-secret-value" not in captured_logs
