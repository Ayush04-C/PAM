"""Framework-independent values used by PAM's availability domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


class CalendarEventValidationError(ValueError):
    """Raised when a calendar event cannot be processed safely."""


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """The minimal calendar information required for availability calculation."""

    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day_date: date | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise CalendarEventValidationError("event title must not be empty")

        is_timed = self.start is not None or self.end is not None
        if is_timed and self.all_day_date is not None:
            raise CalendarEventValidationError(
                "an event must be timed or all-day, not both"
            )
        if not is_timed and self.all_day_date is None:
            raise CalendarEventValidationError("event requires timed or all-day data")
        if is_timed:
            if self.start is None or self.end is None:
                raise CalendarEventValidationError("timed event requires start and end")
            if not _is_aware(self.start) or not _is_aware(self.end):
                raise CalendarEventValidationError(
                    "timed event datetimes must be timezone-aware"
                )
            if self.end <= self.start:
                raise CalendarEventValidationError(
                    "timed event end must be after start"
                )

    @property
    def is_all_day(self) -> bool:
        """Whether this event is an all-day commitment."""
        return self.all_day_date is not None


@dataclass(frozen=True, slots=True)
class TimedInterval:
    """A timezone-aware timed portion of an event belonging to one local day."""

    start: datetime
    end: datetime
    title: str | None = None

    def __post_init__(self) -> None:
        if not _is_aware(self.start) or not _is_aware(self.end):
            raise CalendarEventValidationError(
                "interval datetimes must be timezone-aware"
            )
        if self.end <= self.start:
            raise CalendarEventValidationError("interval end must be after start")

    @property
    def duration(self) -> timedelta:
        """The exact interval duration."""
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class DayAvailability:
    """Calculated availability for a requested local calendar day."""

    day: date
    timed_intervals: tuple[TimedInterval, ...]
    merged_intervals: tuple[TimedInterval, ...]
    all_day_commitments: tuple[str, ...]

    @property
    def busy_duration(self) -> timedelta:
        """Union duration of all timed intervals for the day."""
        return sum(
            (interval.duration for interval in self.merged_intervals), timedelta()
        )

    @property
    def is_free(self) -> bool:
        """Whether the day has neither timed nor all-day commitments."""
        return not self.timed_intervals and not self.all_day_commitments


@dataclass(frozen=True, slots=True)
class WeeklyAvailability:
    """Availability for every date in an inclusive requested range."""

    start_date: date
    end_date: date
    days: tuple[DayAvailability, ...]

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise CalendarEventValidationError(
                "requested end date must not precede start"
            )
