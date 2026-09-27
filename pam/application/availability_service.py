"""Application orchestration for weekly calendar availability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from pam.application.calendar_reader import CalendarReader
from pam.domain import (
    DISPLAY_TIMEZONE,
    calculate_weekly_availability,
    format_weekly_availability,
)

MAX_AVAILABILITY_RANGE_DAYS = 31


class InvalidAvailabilityRequest(ValueError):
    """Raised when a requested availability range is invalid."""


class CalendarUnavailable(RuntimeError):
    """Raised when a calendar reader cannot provide events."""


@dataclass(frozen=True, slots=True)
class AvailabilityService:
    """Retrieve events once and delegate availability work to the domain layer."""

    calendar_reader: CalendarReader

    def get_weekly_availability(
        self, start_date: date, end_date: date, timezone: ZoneInfo = DISPLAY_TIMEZONE
    ) -> str:
        """Return the documented weekly summary for a validated requested range."""
        _validate_request(start_date, end_date, timezone)
        try:
            events = self.calendar_reader.read_events(start_date, end_date, timezone)
        except Exception as error:
            raise CalendarUnavailable("calendar is unavailable") from error

        availability = calculate_weekly_availability(
            start_date, end_date, events, timezone
        )
        return format_weekly_availability(availability)


def _validate_request(start_date: date, end_date: date, timezone: ZoneInfo) -> None:
    if type(start_date) is not date or type(end_date) is not date:
        raise InvalidAvailabilityRequest("start and end must be date values")
    if end_date < start_date:
        raise InvalidAvailabilityRequest("end date must not precede start date")
    if (end_date - start_date).days + 1 > MAX_AVAILABILITY_RANGE_DAYS:
        raise InvalidAvailabilityRequest(
            f"requested range exceeds {MAX_AVAILABILITY_RANGE_DAYS} days"
        )
    if not isinstance(timezone, ZoneInfo) or timezone.key != DISPLAY_TIMEZONE.key:
        raise InvalidAvailabilityRequest("only Asia/Kolkata is supported")
