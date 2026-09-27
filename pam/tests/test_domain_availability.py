"""Unit tests for PAM's local calendar availability domain."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pam.domain import (
    DISPLAY_TIMEZONE,
    CalendarEvent,
    CalendarEventValidationError,
    TimedInterval,
    calculate_weekly_availability,
    format_weekly_availability,
    merge_timed_intervals,
    normalize_timestamp,
)


def timed_event(
    title: str,
    start: datetime,
    end: datetime,
) -> CalendarEvent:
    return CalendarEvent(title=title, start=start, end=end)


def kolkata_datetime(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DISPLAY_TIMEZONE)


def test_empty_week_contains_every_day_and_is_free() -> None:
    availability = calculate_weekly_availability(
        date(2026, 9, 28), date(2026, 10, 4), []
    )

    assert len(availability.days) == 7
    assert all(day.is_free for day in availability.days)
    assert all(day.busy_duration == timedelta() for day in availability.days)


def test_simple_timed_event_contributes_busy_time() -> None:
    day = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        day,
        day,
        [timed_event("Planning", kolkata_datetime(day, 10), kolkata_datetime(day, 11))],
    )

    assert availability.days[0].busy_duration == timedelta(hours=1)
    assert availability.days[0].timed_intervals[0].title == "Planning"


@pytest.mark.parametrize(
    ("intervals", "expected_hours"),
    [
        ([(10, 12), (11, 13)], 3),
        ([(10, 14), (11, 12)], 4),
        ([(10, 11), (11, 12)], 2),
    ],
    ids=["overlapping", "nested", "adjacent"],
)
def test_merge_timed_intervals_unions_overlapping_and_adjacent_ranges(
    intervals: list[tuple[int, int]], expected_hours: int
) -> None:
    day = date(2026, 9, 28)
    merged = merge_timed_intervals(
        TimedInterval(kolkata_datetime(day, start), kolkata_datetime(day, end))
        for start, end in reversed(intervals)
    )

    assert len(merged) == 1
    assert merged[0].duration == timedelta(hours=expected_hours)


def test_event_crossing_one_midnight_is_split_between_days() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday + timedelta(days=1),
        [
            timed_event(
                "Overnight",
                kolkata_datetime(monday, 23),
                kolkata_datetime(monday + timedelta(days=1), 1),
            )
        ],
    )

    assert [day.busy_duration for day in availability.days] == [
        timedelta(hours=1),
        timedelta(hours=1),
    ]


def test_event_crossing_multiple_midnights_is_split_for_each_day() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday + timedelta(days=2),
        [
            timed_event(
                "Trip",
                kolkata_datetime(monday, 23),
                kolkata_datetime(monday + timedelta(days=2), 1),
            )
        ],
    )

    assert [day.busy_duration for day in availability.days] == [
        timedelta(hours=1),
        timedelta(days=1),
        timedelta(hours=1),
    ]


def test_all_day_commitment_prevents_free_day() -> None:
    day = date(2026, 9, 29)
    availability = calculate_weekly_availability(
        day, day, [CalendarEvent("Holiday", all_day_date=day)]
    )

    result = availability.days[0]
    assert result.busy_duration == timedelta()
    assert not result.is_free
    assert result.all_day_commitments == ("Holiday",)


def test_all_day_and_timed_event_remain_distinguishable() -> None:
    day = date(2026, 9, 29)
    availability = calculate_weekly_availability(
        day,
        day,
        [
            CalendarEvent("Holiday", all_day_date=day),
            timed_event("Call", kolkata_datetime(day, 9), kolkata_datetime(day, 10)),
        ],
    )

    result = availability.days[0]
    assert result.busy_duration == timedelta(hours=1)
    assert result.all_day_commitments == ("Holiday",)


def test_supplied_recurring_instances_are_processed_as_ordinary_events() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday + timedelta(days=2),
        [
            timed_event(
                "Standup", kolkata_datetime(monday, 9), kolkata_datetime(monday, 10)
            ),
            timed_event(
                "Standup",
                kolkata_datetime(monday + timedelta(days=1), 9),
                kolkata_datetime(monday + timedelta(days=1), 10),
            ),
        ],
    )

    assert [day.busy_duration for day in availability.days] == [
        timedelta(hours=1),
        timedelta(hours=1),
        timedelta(),
    ]


def test_utc_timestamp_is_normalized_to_kolkata_before_date_calculation() -> None:
    normalized = normalize_timestamp(datetime(2026, 9, 28, 5, tzinfo=UTC))

    assert normalized == kolkata_datetime(date(2026, 9, 28), 10, 30)


def test_dst_source_timezone_uses_zoneinfo_rules() -> None:
    new_york = ZoneInfo("America/New_York")
    normalized = normalize_timestamp(datetime(2026, 3, 8, 3, 30, tzinfo=new_york))

    assert normalized == datetime(2026, 3, 8, 13, tzinfo=DISPLAY_TIMEZONE)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (
            datetime(2026, 9, 28, 11, tzinfo=UTC),
            datetime(2026, 9, 28, 10, tzinfo=UTC),
            "end must be after start",
        ),
        (
            datetime(2026, 9, 28, 10, tzinfo=UTC),
            datetime(2026, 9, 28, 10, tzinfo=UTC),
            "end must be after start",
        ),
        (
            datetime(2026, 9, 28, 10),
            datetime(2026, 9, 28, 11),
            "timezone-aware",
        ),
    ],
    ids=["end-before-start", "zero-length", "naive"],
)
def test_malformed_timed_events_are_rejected(
    start: datetime, end: datetime, message: str
) -> None:
    with pytest.raises(CalendarEventValidationError, match=message):
        CalendarEvent("Invalid", start=start, end=end)


def test_events_completely_outside_range_have_no_effect() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday,
        [
            timed_event(
                "Earlier",
                kolkata_datetime(monday - timedelta(days=1), 10),
                kolkata_datetime(monday - timedelta(days=1), 11),
            )
        ],
    )

    assert availability.days[0].is_free


def test_partially_overlapping_event_is_clipped_to_requested_range() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday,
        [
            timed_event(
                "Overnight",
                kolkata_datetime(monday - timedelta(days=1), 23),
                kolkata_datetime(monday, 2),
            )
        ],
    )

    interval = availability.days[0].timed_intervals[0]
    assert interval.start == kolkata_datetime(monday, 0)
    assert interval.end == kolkata_datetime(monday, 2)


def test_unsorted_event_input_produces_sorted_day_events() -> None:
    day = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        day,
        day,
        [
            timed_event("Later", kolkata_datetime(day, 16), kolkata_datetime(day, 17)),
            timed_event(
                "Earlier", kolkata_datetime(day, 10), kolkata_datetime(day, 11)
            ),
        ],
    )

    assert [interval.title for interval in availability.days[0].timed_intervals] == [
        "Earlier",
        "Later",
    ]


def test_weekly_formatter_matches_documented_golden_output() -> None:
    monday = date(2026, 9, 28)
    availability = calculate_weekly_availability(
        monday,
        monday + timedelta(days=2),
        [
            timed_event(
                "Assignment discussion",
                kolkata_datetime(monday, 16),
                kolkata_datetime(monday, 17),
            ),
            timed_event(
                "Team meeting",
                kolkata_datetime(monday, 10),
                kolkata_datetime(monday, 11),
            ),
            CalendarEvent("Holiday", all_day_date=monday + timedelta(days=1)),
        ],
    )

    expected = "\n".join(
        [
            "Your next week: 28 Sep\N{EM DASH}30 Sep",
            "",
            "Mon, 28 Sep \N{EM DASH} 2 hours busy",
            "\N{BULLET} 10:00\N{EM DASH}11:00 \N{EM DASH} Team meeting",
            "\N{BULLET} 16:00\N{EM DASH}17:00 \N{EM DASH} Assignment discussion",
            "",
            "Tue, 29 Sep \N{EM DASH} 0 hours busy",
            "\N{BULLET} All-day commitment \N{EM DASH} Holiday",
            "",
            "Wed, 30 Sep \N{EM DASH} 0 hours busy \N{EM DASH} Free day",
            "\N{BULLET} No events",
        ]
    )

    assert format_weekly_availability(availability) == expected
