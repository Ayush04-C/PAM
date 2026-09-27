"""Print a local Phase 2 weekly availability demonstration."""

from datetime import date, datetime, timedelta

from pam.application import AvailabilityService, FakeCalendarReader
from pam.domain import DISPLAY_TIMEZONE, CalendarEvent


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=DISPLAY_TIMEZONE)


def main() -> None:
    """Print the documented local fake-calendar summary."""
    monday = date(2026, 9, 28)
    reader = FakeCalendarReader(
        [
            CalendarEvent("Lecture", _at(monday, 10), _at(monday, 12)),
            CalendarEvent("Project Meeting", _at(monday, 11), _at(monday, 13)),
            CalendarEvent(
                "Late Work",
                _at(monday + timedelta(days=2), 23),
                _at(monday + timedelta(days=3), 1),
            ),
            CalendarEvent("Institute Event", all_day_date=monday + timedelta(days=4)),
        ]
    )
    service = AvailabilityService(reader)
    print(service.get_weekly_availability(monday, monday + timedelta(days=6)))


if __name__ == "__main__":
    main()
