"""Read-only calendar-reader contract and local in-memory implementation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from pam.domain import DISPLAY_TIMEZONE, CalendarEvent, normalize_timestamp


@runtime_checkable
class CalendarReader(Protocol):
    """Read calendar events for an inclusive local date range."""

    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        """Return calendar events relevant to the requested range."""


@dataclass(frozen=True, slots=True)
class FakeCalendarReader:
    """Deterministic in-memory CalendarReader for local development and tests."""

    events: tuple[CalendarEvent, ...]

    def __init__(self, events: Iterable[CalendarEvent] = ()) -> None:
        object.__setattr__(self, "events", tuple(events))

    def read_events(
        self,
        start_date: date,
        end_date: date,
        timezone: ZoneInfo = DISPLAY_TIMEZONE,
    ) -> tuple[CalendarEvent, ...]:
        """Return only events with any all-day or timed range overlap."""
        range_start = datetime.combine(start_date, time.min, tzinfo=timezone)
        range_end = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=timezone
        )
        return tuple(
            event
            for event in self.events
            if _event_overlaps_range(
                event, start_date, end_date, range_start, range_end, timezone
            )
        )


def _event_overlaps_range(
    event: CalendarEvent,
    start_date: date,
    end_date: date,
    range_start: datetime,
    range_end: datetime,
    timezone: ZoneInfo,
) -> bool:
    if event.is_all_day:
        assert event.all_day_date is not None
        return start_date <= event.all_day_date <= end_date

    assert event.start is not None and event.end is not None
    normalized_start = normalize_timestamp(event.start, timezone)
    normalized_end = normalize_timestamp(event.end, timezone)
    return normalized_start < range_end and normalized_end > range_start
