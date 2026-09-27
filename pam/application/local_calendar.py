"""Deterministic local CalendarReader wiring for Phase 3 development."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pam.application.availability_service import AvailabilityService
from pam.application.calendar_reader import FakeCalendarReader
from pam.domain import DISPLAY_TIMEZONE, CalendarEvent


def create_local_availability_service() -> AvailabilityService:
    """Create the local service backed by documented fake calendar events."""
    monday = date(2026, 9, 28)
    return AvailabilityService(
        FakeCalendarReader(
            [
                CalendarEvent("Lecture", _at(monday, 10), _at(monday, 12)),
                CalendarEvent("Project Meeting", _at(monday, 11), _at(monday, 13)),
                CalendarEvent(
                    "Late Work",
                    _at(monday + timedelta(days=2), 23),
                    _at(monday + timedelta(days=3), 1),
                ),
                CalendarEvent(
                    "Institute Event", all_day_date=monday + timedelta(days=4)
                ),
            ]
        )
    )


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=DISPLAY_TIMEZONE)
