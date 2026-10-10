"""Offline integration tests for PAM's single read-only Calendar MCP tool."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError

from pam.application import AvailabilityService, FakeCalendarReader
from pam.application.local_calendar import create_local_availability_service
from pam.domain import DISPLAY_TIMEZONE, CalendarEvent
from pam.integrations.google_calendar import GoogleReconnectRequired
from pam.mcp.calendar import create_calendar_mcp_server
from pam.mcp.config import local_stdio_launch_config

REQUEST = {
    "start_date": "2026-09-28",
    "end_date": "2026-10-04",
    "timezone": "Asia/Kolkata",
}


class FailingReader:
    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        raise RuntimeError("REFRESH_TOKEN_DO_NOT_LOG")


class ReconnectReader:
    def read_events(
        self, start_date: date, end_date: date, timezone: ZoneInfo
    ) -> tuple[CalendarEvent, ...]:
        raise GoogleReconnectRequired("REFRESH_TOKEN_DO_NOT_LOG")


def fake_service() -> AvailabilityService:
    return AvailabilityService(
        FakeCalendarReader(
            (
                CalendarEvent(
                    "Overlap one",
                    datetime(2026, 9, 28, 10, tzinfo=DISPLAY_TIMEZONE),
                    datetime(2026, 9, 28, 12, tzinfo=DISPLAY_TIMEZONE),
                ),
                CalendarEvent(
                    "Overlap two",
                    datetime(2026, 9, 28, 11, tzinfo=DISPLAY_TIMEZONE),
                    datetime(2026, 9, 28, 13, tzinfo=DISPLAY_TIMEZONE),
                ),
                CalendarEvent(
                    "Cross midnight",
                    datetime(2026, 9, 30, 23, tzinfo=DISPLAY_TIMEZONE),
                    datetime(2026, 10, 1, 1, tzinfo=DISPLAY_TIMEZONE),
                ),
                CalendarEvent("All day", all_day_date=date(2026, 10, 2)),
            )
        )
    )


@pytest.mark.asyncio
async def test_discovery_exposes_exactly_one_read_only_calendar_tool() -> None:
    server = create_calendar_mcp_server(fake_service())

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == ["get_weekly_availability"]
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.input_schema["additionalProperties"] is False
    assert set(tool.input_schema["properties"]) == {
        "start_date",
        "end_date",
        "timezone",
        "minimum_duration_minutes",
        "requested_time",
    }
    assert tool.output_schema is not None
    assert tool.output_schema["additionalProperties"] is False
    assert tool.output_schema["required"] == ["availability", "presentation"]
    assert set(tool.output_schema["properties"]) == {"availability", "presentation"}
    assert "READ ONLY" in tool.description


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    (
        {"end_date": "2026-10-04", "timezone": "Asia/Kolkata"},
        {"start_date": "2026-09-28", "timezone": "Asia/Kolkata"},
        {"start_date": "2026-09-28", "end_date": "2026-10-04"},
        {**REQUEST, "start_date": "not-a-date"},
        {**REQUEST, "timezone": 5},
        {**REQUEST, "unexpected": "REFRESH_TOKEN_DO_NOT_LOG"},
    ),
)
async def test_mcp_input_rejects_invalid_or_unknown_fields(
    arguments: dict[str, object],
) -> None:
    server = create_calendar_mcp_server(fake_service())

    with pytest.raises(ToolError) as error:
        await server.call_tool("get_weekly_availability", arguments)

    assert "REFRESH_TOKEN_DO_NOT_LOG" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    (
        {**REQUEST, "start_date": "2026-10-04", "end_date": "2026-09-28"},
        {**REQUEST, "end_date": "2026-11-01"},
        {**REQUEST, "timezone": "Europe/London"},
    ),
)
async def test_business_invalid_requests_reach_application_and_fail_safely(
    arguments: dict[str, str],
) -> None:
    server = create_calendar_mcp_server(fake_service())

    with pytest.raises(ToolError, match="invalid availability request"):
        await server.call_tool("get_weekly_availability", arguments)


@pytest.mark.asyncio
async def test_mcp_output_is_exactly_the_direct_service_result() -> None:
    service = fake_service()
    server = create_calendar_mcp_server(service)

    result = await server.call_tool("get_weekly_availability", REQUEST)
    direct = service.get_weekly_availability(
        date(2026, 9, 28), date(2026, 10, 4), DISPLAY_TIMEZONE
    )

    assert result.structured_content["availability"] == direct
    assert result.structured_content["presentation"]["timezone"] == "Asia/Kolkata"
    assert "3 hours busy" in direct
    assert "Free day" in direct
    assert "23:00" in direct
    assert "All-day commitment" in direct


@pytest.mark.asyncio
async def test_sdk_client_integrates_with_the_injected_fake_calendar_server() -> None:
    service = fake_service()
    server = create_calendar_mcp_server(service)

    async with Client(server) as client:
        tools = await client.list_tools()
        result = await client.call_tool("get_weekly_availability", REQUEST)

    direct = service.get_weekly_availability(
        date(2026, 9, 28), date(2026, 10, 4), DISPLAY_TIMEZONE
    )
    assert [tool.name for tool in tools.tools] == ["get_weekly_availability"]
    assert result.structured_content["availability"] == direct
    assert result.structured_content["presentation"]["timezone"] == "Asia/Kolkata"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_stdio_client_runs_the_configured_fake_calendar_mcp_server() -> None:
    launch_config = local_stdio_launch_config(sys.executable)
    server_environment = {**os.environ, "PAM_CALENDAR_BACKEND": "fake"}
    launch = StdioServerParameters(
        command=launch_config.command,
        args=list(launch_config.args),
        cwd=Path(__file__).parents[2],
        env=server_environment,
    )

    async with Client(launch) as client:
        tools = await client.list_tools()
        result = await client.call_tool("get_weekly_availability", REQUEST)

    direct = create_local_availability_service().get_weekly_availability(
        date(2026, 9, 28), date(2026, 10, 4), DISPLAY_TIMEZONE
    )
    assert launch_config.transport == "stdio"
    assert [tool.name for tool in tools.tools] == ["get_weekly_availability"]
    assert result.structured_content["availability"] == direct
    assert result.structured_content["presentation"]["timezone"] == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_calendar_unavailable_is_a_safe_tool_error_without_secret_leakage() -> (
    None
):
    server = create_calendar_mcp_server(AvailabilityService(FailingReader()))

    with pytest.raises(ToolError) as error:
        await server.call_tool("get_weekly_availability", REQUEST)

    assert str(error.value) == (
        "Error executing tool get_weekly_availability: "
        "calendar is unavailable; reconnection may be required"
    )
    assert "REFRESH_TOKEN_DO_NOT_LOG" not in str(error.value)


@pytest.mark.asyncio
async def test_google_reconnect_requirement_is_a_safe_tool_error() -> None:
    server = create_calendar_mcp_server(AvailabilityService(ReconnectReader()))

    with pytest.raises(ToolError) as error:
        await server.call_tool("get_weekly_availability", REQUEST)

    assert "reconnection may be required" in str(error.value)
    assert "REFRESH_TOKEN_DO_NOT_LOG" not in str(error.value)


@pytest.mark.asyncio
async def test_no_write_or_credential_tools_are_discoverable() -> None:
    server = create_calendar_mcp_server(fake_service())

    names = {tool.name for tool in await server.list_tools()}

    assert names == {"get_weekly_availability"}
    assert names.isdisjoint(
        {
            "create_event",
            "update_event",
            "delete_event",
            "modify_event",
            "insert_event",
            "list_events",
            "get_events",
            "search_calendar",
            "get_credentials",
            "manage_credentials",
        }
    )


@pytest.mark.asyncio
async def test_mcp_returns_deterministic_free_windows_and_duration_candidates() -> None:
    day = date(2026, 10, 6)
    service = AvailabilityService(
        FakeCalendarReader(
            (
                CalendarEvent(
                    "Class",
                    datetime(2026, 10, 6, 9, 30, tzinfo=DISPLAY_TIMEZONE),
                    datetime(2026, 10, 6, 12, 30, tzinfo=DISPLAY_TIMEZONE),
                ),
                CalendarEvent(
                    "Lab",
                    datetime(2026, 10, 6, 14, tzinfo=DISPLAY_TIMEZONE),
                    datetime(2026, 10, 6, 17, tzinfo=DISPLAY_TIMEZONE),
                ),
            )
        )
    )
    server = create_calendar_mcp_server(service)

    result = await server.call_tool(
        "get_weekly_availability",
        {
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "timezone": "Asia/Kolkata",
            "minimum_duration_minutes": 60,
            "requested_time": "13:00",
        },
    )

    presentation = result.structured_content["presentation"]
    assert isinstance(presentation, dict)
    day_result = presentation["days"][0]
    assert isinstance(day_result, dict)
    assert day_result["requested_time_is_free"] is True
    assert {window["label"] for window in day_result["free_windows"]} == {
        "Before 09:30",
        "12:30–14:00",
        "After 17:00",
    }
    assert day_result["candidate_slots"] == [
        {"start": "12:30", "end": "13:30", "label": "12:30–13:30"},
    ]


@pytest.mark.asyncio
async def test_mcp_rejects_requested_time_for_multiple_days() -> None:
    server = create_calendar_mcp_server(fake_service())

    with pytest.raises(ToolError, match="requested time requires a single"):
        await server.call_tool(
            "get_weekly_availability", {**REQUEST, "requested_time": "13:00"}
        )
