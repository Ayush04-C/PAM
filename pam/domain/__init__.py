"""Pure, framework-independent availability domain code."""

from pam.domain.availability import (
    DISPLAY_TIMEZONE,
    calculate_weekly_availability,
    merge_timed_intervals,
    normalize_timestamp,
    split_interval_by_day,
)
from pam.domain.formatter import format_weekly_availability
from pam.domain.models import (
    CalendarEvent,
    CalendarEventValidationError,
    DayAvailability,
    TimedInterval,
    WeeklyAvailability,
)

__all__ = [
    "DISPLAY_TIMEZONE",
    "CalendarEvent",
    "CalendarEventValidationError",
    "DayAvailability",
    "TimedInterval",
    "WeeklyAvailability",
    "calculate_weekly_availability",
    "format_weekly_availability",
    "merge_timed_intervals",
    "normalize_timestamp",
    "split_interval_by_day",
]
