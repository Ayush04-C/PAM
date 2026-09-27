"""Deterministic text formatting for weekly availability."""

from __future__ import annotations

from datetime import date, timedelta

from pam.domain.models import DayAvailability, WeeklyAvailability

_BULLET = "\N{BULLET}"
_EM_DASH = "\N{EM DASH}"


def format_weekly_availability(availability: WeeklyAvailability) -> str:
    """Format availability using the documented weekly layout."""
    date_range = _format_range(availability.start_date, availability.end_date)
    lines = [f"Your next week: {date_range}"]
    for day in availability.days:
        lines.extend(("", _format_day(day)))
        lines.extend(_format_commitments(day))
    return "\n".join(lines)


def _format_range(start_date: date, end_date: date) -> str:
    if start_date == end_date:
        return _format_date(start_date)
    return f"{_format_date(start_date)}{_EM_DASH}{_format_date(end_date)}"


def _format_date(value: date) -> str:
    return f"{value.day} {value.strftime('%b')}"


def _format_day(day: DayAvailability) -> str:
    line = (
        f"{day.day.strftime('%a')}, {_format_date(day.day)} {_EM_DASH} "
        f"{_format_duration(day.busy_duration)} busy"
    )
    if day.is_free:
        return f"{line} {_EM_DASH} Free day"
    return line


def _format_commitments(day: DayAvailability) -> tuple[str, ...]:
    if day.is_free:
        return (f"{_BULLET} No events",)

    lines = [
        f"{_BULLET} {interval.start.strftime('%H:%M')}{_EM_DASH}"
        f"{interval.end.strftime('%H:%M')} {_EM_DASH} {interval.title}"
        for interval in day.timed_intervals
    ]
    lines.extend(
        f"{_BULLET} All-day commitment {_EM_DASH} {title}"
        for title in day.all_day_commitments
    )
    return tuple(lines)


def _format_duration(duration: timedelta) -> str:
    total_minutes = duration.days * 24 * 60 + duration.seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    if minutes == 0:
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if minutes in {15, 30, 45}:
        fraction = {15: "25", 30: "5", 45: "75"}[minutes]
        return f"{hours}.{fraction} hours"
    hour_label = "hour" if hours == 1 else "hours"
    minute_label = "minute" if minutes == 1 else "minutes"
    return f"{hours} {hour_label} {minutes} {minute_label}"
