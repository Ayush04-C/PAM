"""A minimal read-only MCP adapter around AvailabilityService."""

from __future__ import annotations

from datetime import date
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from mcp_types import ToolAnnotations
from pydantic import ConfigDict, ValidationError, field_validator
from pydantic.config import ExtraValues

from pam.application import (
    AvailabilityService,
    CalendarUnavailable,
    InvalidAvailabilityRequest,
)

_TOOL_NAME = "get_weekly_availability"
_TOOL_DESCRIPTION = (
    "Read weekly Calendar availability for an explicitly requested range. "
    "READ ONLY: this tool cannot modify Calendar data. It accepts only validated "
    "explicit ranges; application range limits apply. The current v1 display "
    "timezone is Asia/Kolkata. Calendar data may be unavailable or require "
    "reconnection."
)


class WeeklyAvailabilityRequest(ArgModelBase):
    """Strict MCP arguments while keeping business validation in the application."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    timezone: str

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        extra: ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        """Hide rejected caller values, which may accidentally be sensitive."""
        try:
            return super().model_validate(
                obj,
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            raise ToolError("invalid tool input") from error

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def require_iso_date(cls, value: object) -> object:
        """Accept only ISO calendar-date strings at the MCP boundary."""
        if not isinstance(value, str):
            raise ValueError("date must be an ISO date string")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("date must be an ISO date string") from error
        return value

    @field_validator("timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        """Reject malformed timezone identifiers without duplicating policy rules."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value


class WeeklyAvailabilityResponse(ArgModelBase):
    """Minimal structured MCP output containing the application summary verbatim."""

    model_config = ConfigDict(extra="forbid")

    availability: str


class CalendarMcpAdapter:
    """Delegate the single MCP operation to an explicitly injected service."""

    def __init__(self, availability_service: AvailabilityService) -> None:
        self._availability_service = availability_service

    def get_weekly_availability(
        self, start_date: date, end_date: date, timezone: str
    ) -> WeeklyAvailabilityResponse:
        """Return the exact deterministic AvailabilityService result."""
        try:
            summary = self._availability_service.get_weekly_availability(
                start_date, end_date, ZoneInfo(timezone)
            )
        except InvalidAvailabilityRequest as error:
            raise ToolError("invalid availability request") from error
        except CalendarUnavailable as error:
            raise ToolError(
                "calendar is unavailable; reconnection may be required"
            ) from error
        return WeeklyAvailabilityResponse(availability=summary)


def create_calendar_mcp_server(availability_service: AvailabilityService) -> MCPServer:
    """Create a one-tool MCP server bound only to AvailabilityService."""
    adapter = CalendarMcpAdapter(availability_service)
    tool = Tool.from_function(
        adapter.get_weekly_availability,
        name=_TOOL_NAME,
        description=_TOOL_DESCRIPTION,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    tool.fn_metadata.arg_model = WeeklyAvailabilityRequest
    tool.parameters = WeeklyAvailabilityRequest.model_json_schema()
    return MCPServer(
        name="PAM Calendar",
        description="Private read-only Calendar availability tools.",
        tools=[tool],
    )
