"""Narrow, allowlisted client for PAM's local Calendar MCP server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from mcp import Client
from mcp.server import MCPServer

from pam.conversation.models import ToolDefinition
from pam.mcp.config import McpServerLaunchConfig

_TOOL_NAME = "get_weekly_availability"


class McpUnavailable(RuntimeError):
    """The private Calendar MCP boundary could not be used safely."""


class CalendarMcpClient(Protocol):
    """Only the approved Calendar capability exposed to Phase 6."""

    async def discover_tools(self) -> tuple[ToolDefinition, ...]:
        """Return the approved tool's schema if the MCP server offers it."""

    async def get_weekly_availability(
        self, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Invoke the only approved MCP method with unmodified arguments."""


class LocalCalendarMcpClient:
    """Open short-lived MCP sessions without offering arbitrary tool execution."""

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def discover_tools(self) -> tuple[ToolDefinition, ...]:
        try:
            async with Client(self._server) as client:
                discovered = await client.list_tools()
        except Exception as error:
            raise McpUnavailable("calendar assistant is unavailable") from error
        tools = tuple(
            ToolDefinition(tool.name, tool.description or "", tool.input_schema)
            for tool in discovered.tools
            if tool.name == _TOOL_NAME
        )
        if len(tools) != 1:
            raise McpUnavailable("calendar assistant is unavailable")
        return tools

    async def get_weekly_availability(
        self, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        try:
            async with Client(self._server) as client:
                response = await client.call_tool(_TOOL_NAME, dict(arguments))
        except Exception as error:
            raise McpUnavailable("calendar assistant is unavailable") from error
        if response.is_error or not isinstance(response.structured_content, dict):
            raise McpUnavailable("calendar assistant is unavailable")
        availability = response.structured_content.get("availability")
        if not isinstance(availability, str):
            raise McpUnavailable("calendar assistant is unavailable")
        return {"availability": availability}


def local_client_from_server(server: MCPServer) -> LocalCalendarMcpClient:
    """Create an injected local MCP client, primarily for tests and CLI wiring."""
    return LocalCalendarMcpClient(server)


def launch_config_for_cli(python_executable: str) -> McpServerLaunchConfig:
    """Expose the Phase 5 command without expanding Calendar permissions."""
    from pam.mcp.config import local_stdio_launch_config

    return local_stdio_launch_config(python_executable)
