"""Tests for the Phase 2 application availability service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pam.application import (
    MAX_AVAILABILITY_RANGE_DAYS,
    AvailabilityService,
    CalendarReader,
    CalendarUnavailable,
    FakeCalendarReader,
    InvalidAvailabilityRequest,
)
from pam.domain import (
    DISPLAY_TIMEZONE,
    CalendarEvent,
    calculate_weekly_availability,
    format_weekly_availability,
)


def at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=DISPLAY_TIMEZONE)


@dataclass
class RecordingReader:
    events: tuple[CalendarEvent, ...] = ()
    calls: list[tuple[date, date, ZoneInfo]] = field(default_factory=list)

    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        self.calls.append((start_date, end_date, timezone))
        return self.events


class FailingReader:
    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        raise RuntimeError("source unavailable")


def test_service_calls_reader_once_with_exact_validated_request() -> None:
    monday = date(2026, 9, 28)
    reader = RecordingReader()

    AvailabilityService(reader).get_weekly_availability(
        monday, monday + timedelta(days=6)
    )

    assert reader.calls == [(monday, monday + timedelta(days=6), DISPLAY_TIMEZONE)]


@pytest.mark.parametrize(
    ("start_date", "end_date", "timezone"),
    [
        (date(2026, 10, 10), date(2026, 10, 1), DISPLAY_TIMEZONE),
        (
            date(2026, 9, 1),
            date(2026, 9, 1) + timedelta(days=MAX_AVAILABILITY_RANGE_DAYS),
            DISPLAY_TIMEZONE,
        ),
        (date(2026, 9, 28), date(2026, 10, 4), ZoneInfo("UTC")),
    ],
    ids=["reversed", "too-long", "unsupported-timezone"],
)
def test_invalid_request_never_reaches_reader(
    start_date: date, end_date: date, timezone: ZoneInfo
) -> None:
    reader = RecordingReader()

    with pytest.raises(InvalidAvailabilityRequest):
        AvailabilityService(reader).get_weekly_availability(
            start_date, end_date, timezone
        )

    assert reader.calls == []


def test_reader_failure_is_mapped_to_stable_application_error() -> None:
    monday = date(2026, 9, 28)

    with pytest.raises(CalendarUnavailable, match="calendar is unavailable") as error:
        AvailabilityService(FailingReader()).get_weekly_availability(monday, monday)

    assert isinstance(error.value.__cause__, RuntimeError)


def test_fake_reader_is_a_calendar_reader_and_is_deterministic() -> None:
    monday = date(2026, 9, 28)
    event = CalendarEvent("Call", at(monday, 10), at(monday, 11))
    reader = FakeCalendarReader([event])

    assert isinstance(reader, CalendarReader)
    assert reader.read_events(monday, monday, DISPLAY_TIMEZONE) == (event,)
    assert reader.read_events(monday, monday, DISPLAY_TIMEZONE) == (event,)


def test_fake_reader_excludes_events_outside_the_requested_range() -> None:
    monday = date(2026, 9, 28)
    reader = FakeCalendarReader(
        [
            CalendarEvent(
                "Earlier",
                at(monday - timedelta(days=1), 10),
                at(monday - timedelta(days=1), 11),
            ),
            CalendarEvent("Inside", at(monday, 10), at(monday, 11)),
        ]
    )

    assert [
        event.title for event in reader.read_events(monday, monday, DISPLAY_TIMEZONE)
    ] == ["Inside"]


def test_service_output_equals_direct_phase_one_output() -> None:
    monday = date(2026, 9, 28)
    events = (
        CalendarEvent("Lecture", at(monday, 10), at(monday, 12)),
        CalendarEvent("Project Meeting", at(monday, 11), at(monday, 13)),
        CalendarEvent("Institute Event", all_day_date=monday + timedelta(days=4)),
    )
    service_output = AvailabilityService(
        FakeCalendarReader(events)
    ).get_weekly_availability(monday, monday + timedelta(days=6))
    direct_output = format_weekly_availability(
        calculate_weekly_availability(monday, monday + timedelta(days=6), events)
    )

    assert service_output == direct_output


def test_empty_fake_calendar_preserves_free_day_output() -> None:
    monday = date(2026, 9, 28)

    output = AvailabilityService(FakeCalendarReader()).get_weekly_availability(
        monday, monday
    )

    assert "0 hours busy — Free day" in output
    assert "• No events" in output


def test_overlap_and_all_day_behavior_are_preserved_through_service() -> None:
    monday = date(2026, 9, 28)
    output = AvailabilityService(
        FakeCalendarReader(
            [
                CalendarEvent("Lecture", at(monday, 10), at(monday, 12)),
                CalendarEvent("Meeting", at(monday, 11), at(monday, 13)),
                CalendarEvent("Holiday", all_day_date=monday + timedelta(days=1)),
            ]
        )
    ).get_weekly_availability(monday, monday + timedelta(days=1))

    assert "Mon, 28 Sep — 3 hours busy" in output
    assert "Tue, 29 Sep — 0 hours busy — Free day" not in output
    assert "• All-day commitment — Holiday" in output
