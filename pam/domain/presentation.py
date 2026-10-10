"""Deterministic presentation facts derived from Calendar availability."""

from __future__ import annotations

from datetime import time, timedelta

from pam.domain.models import DayAvailability, TimedInterval, WeeklyAvailability


def build_availability_presentation(
    availability: WeeklyAvailability,
    *,
    minimum_duration_minutes: int | None = None,
    requested_time: time | None = None,
) -> dict[str, object]:
    """Build provider-neutral Calendar facts without creating another truth source."""
    required_duration = (
        timedelta(minutes=minimum_duration_minutes)
        if minimum_duration_minutes is not None
        else None
    )
    days = tuple(
        _present_day(day, required_duration, requested_time)
        for day in availability.days
    )
    effective_busy = {
        day.day: 24 * 60 if day.all_day_commitments else _minutes(day.busy_duration)
        for day in availability.days
    }
    min_busy = min(effective_busy.values(), default=0)
    max_busy = max(effective_busy.values(), default=0)
    return {
        "timezone": "Asia/Kolkata",
        "start_date": availability.start_date.isoformat(),
        "end_date": availability.end_date.isoformat(),
        "days": days,
        "weekly": {
            "free_days": tuple(
                day.day.isoformat() for day in availability.days if day.is_free
            ),
            "busiest_days": tuple(
                day.day.isoformat()
                for day in availability.days
                if effective_busy[day.day] == max_busy
            ),
            "openest_days": tuple(
                day.day.isoformat()
                for day in availability.days
                if effective_busy[day.day] == min_busy
            ),
        },
    }


def _present_day(
    day: DayAvailability,
    required_duration: timedelta | None,
    requested_time: time | None,
) -> dict[str, object]:
    free_windows = day.free_intervals
    candidate_slots = _candidate_slots(day, free_windows, required_duration)
    result: dict[str, object] = {
        "date": day.day.isoformat(),
        "weekday": day.day.strftime("%a"),
        "busy_minutes": _minutes(day.busy_duration),
        "is_free_day": day.is_free,
        "events": tuple(
            {
                "start": interval.start.strftime("%H:%M"),
                "end": interval.end.strftime("%H:%M"),
                "title": interval.title or "Untitled event",
            }
            for interval in day.timed_intervals
        ),
        "all_day_commitments": day.all_day_commitments,
        "free_windows": tuple(
            _present_interval(interval, day) for interval in free_windows
        ),
        "candidate_slots": tuple(
            _present_slot(interval) for interval in candidate_slots
        ),
    }
    if requested_time is not None:
        result["requested_time"] = requested_time.strftime("%H:%M")
        result["requested_time_is_free"] = _time_is_free(day, requested_time)
    return result


def _present_interval(interval: TimedInterval, day: DayAvailability) -> dict[str, str]:
    start = interval.start.strftime("%H:%M")
    end = interval.end.strftime("%H:%M")
    if interval.start.time() == time.min and interval.end.date() > day.day:
        label = "Free all day"
    elif interval.start.time() == time.min:
        label = f"Before {end}"
    elif interval.end.date() > day.day:
        label = f"After {start}"
    else:
        label = f"{start}–{end}"
    return {"start": start, "end": end, "label": label}


def _candidate_slots(
    day: DayAvailability,
    free_windows: tuple[TimedInterval, ...],
    required_duration: timedelta | None,
) -> tuple[TimedInterval, ...]:
    """Return only explicit, bounded slots that Python can recommend exactly.

    Open-ended human-facing windows such as "before 09:30" and "after 12:30"
    remain availability facts, but do not authorize an arbitrary model-selected
    start or end time. PAM deliberately avoids inventing working hours to turn
    those boundary windows into meeting suggestions.
    """
    if required_duration is None:
        return ()
    slots: list[TimedInterval] = []
    for window in free_windows:
        if not _is_bounded_within_day(window, day):
            continue
        slot_end = window.start + required_duration
        if slot_end <= window.end:
            slots.append(TimedInterval(window.start, slot_end))
    return tuple(slots)


def _is_bounded_within_day(interval: TimedInterval, day: DayAvailability) -> bool:
    return (
        interval.start.date() == day.day
        and interval.start.time() != time.min
        and interval.end.date() == day.day
    )


def _present_slot(interval: TimedInterval) -> dict[str, str]:
    start = interval.start.strftime("%H:%M")
    end = interval.end.strftime("%H:%M")
    return {"start": start, "end": end, "label": f"{start}–{end}"}


def _time_is_free(day: DayAvailability, requested_time: time) -> bool:
    if day.all_day_commitments:
        return False
    return not any(
        interval.start.time() <= requested_time < interval.end.time()
        for interval in day.merged_intervals
    )


def _minutes(value: timedelta) -> int:
    return value.days * 24 * 60 + value.seconds // 60
