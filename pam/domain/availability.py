"""Pure timezone-aware availability calculation functions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pam.domain.models import (
    CalendarEvent,
    CalendarEventValidationError,
    DayAvailability,
    TimedInterval,
    WeeklyAvailability,
)

DISPLAY_TIMEZONE = ZoneInfo("Asia/Kolkata")


def normalize_timestamp(
    timestamp: datetime, timezone: ZoneInfo = DISPLAY_TIMEZONE
) -> datetime:
    """Convert an aware timestamp to PAM's display timezone."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CalendarEventValidationError("event timestamp must be timezone-aware")
    return timestamp.astimezone(timezone)


def split_interval_by_day(interval: TimedInterval) -> tuple[TimedInterval, ...]:
    """Split a normalized interval at local midnight boundaries."""
    pieces: list[TimedInterval] = []
    cursor = interval.start
    while cursor.date() < interval.end.date():
        next_midnight = datetime.combine(
            cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo
        )
        pieces.append(TimedInterval(cursor, next_midnight, interval.title))
        cursor = next_midnight
    pieces.append(TimedInterval(cursor, interval.end, interval.title))
    return tuple(pieces)


def merge_timed_intervals(
    intervals: Iterable[TimedInterval],
) -> tuple[TimedInterval, ...]:
    """Sort and merge overlapping, nested, and adjacent day intervals."""
    ordered = sorted(intervals, key=lambda interval: (interval.start, interval.end))
    if not ordered:
        return ()

    day = ordered[0].start.date()
    if any(interval.start.date() != day for interval in ordered):
        raise CalendarEventValidationError("intervals must belong to one local day")

    merged: list[TimedInterval] = []
    current_start = ordered[0].start
    current_end = ordered[0].end
    for interval in ordered[1:]:
        if interval.start <= current_end:
            current_end = max(current_end, interval.end)
            continue
        merged.append(TimedInterval(current_start, current_end))
        current_start = interval.start
        current_end = interval.end
    merged.append(TimedInterval(current_start, current_end))
    return tuple(merged)


def calculate_weekly_availability(
    start_date: date,
    end_date: date,
    events: Iterable[CalendarEvent],
    timezone: ZoneInfo = DISPLAY_TIMEZONE,
) -> WeeklyAvailability:
    """Calculate local availability for every date in an inclusive range."""
    if end_date < start_date:
        raise CalendarEventValidationError("requested end date must not precede start")

    range_start = datetime.combine(start_date, time.min, tzinfo=timezone)
    range_end = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=timezone
    )
    timed_by_day: defaultdict[date, list[TimedInterval]] = defaultdict(list)
    all_day_by_day: defaultdict[date, list[str]] = defaultdict(list)

    for event in events:
        if event.is_all_day:
            assert event.all_day_date is not None
            if start_date <= event.all_day_date <= end_date:
                all_day_by_day[event.all_day_date].append(event.title)
            continue

        assert event.start is not None and event.end is not None
        normalized_start = normalize_timestamp(event.start, timezone)
        normalized_end = normalize_timestamp(event.end, timezone)
        clipped_start = max(normalized_start, range_start)
        clipped_end = min(normalized_end, range_end)
        if clipped_start >= clipped_end:
            continue

        for piece in split_interval_by_day(
            TimedInterval(clipped_start, clipped_end, event.title)
        ):
            timed_by_day[piece.start.date()].append(piece)

    days: list[DayAvailability] = []
    current_day = start_date
    while current_day <= end_date:
        timed_intervals = tuple(
            sorted(timed_by_day[current_day], key=lambda interval: interval.start)
        )
        days.append(
            DayAvailability(
                day=current_day,
                timed_intervals=timed_intervals,
                merged_intervals=merge_timed_intervals(timed_intervals),
                all_day_commitments=tuple(sorted(all_day_by_day[current_day])),
            )
        )
        current_day += timedelta(days=1)

    return WeeklyAvailability(start_date, end_date, tuple(days))
