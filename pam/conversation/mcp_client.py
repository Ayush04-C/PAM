"""Separate allowlisted clients for the shared private Calendar/Drive server."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mcp import Client
from mcp.server import MCPServer

from pam.config import Settings
from pam.conversation.models import DriveConsent, ToolDefinition
from pam.mcp.config import McpServerLaunchConfig
from pam.memory.models import MemoryOwnerId

_TOOL_NAME = "get_weekly_availability"
DRIVE_TOOLS = frozenset({"drive_search_files", "drive_get_file_metadata"})


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
        presentation = response.structured_content.get("presentation")
        if not isinstance(availability, str) or not isinstance(presentation, dict):
            raise McpUnavailable("calendar assistant is unavailable")
        return {"availability": availability, "presentation": presentation}


class DriveMcpClient(Protocol):
    async def discover_tools(self) -> tuple[ToolDefinition, ...]: ...

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        owner: MemoryOwnerId,
    ) -> Mapping[str, Any]: ...


class LocalDriveMcpClient:
    """Fixed private operator identity; only validated metadata methods exist."""

    def __init__(self, server: MCPServer, owner: MemoryOwnerId) -> None:
        self._server = server
        self._owner = owner

    async def discover_tools(self) -> tuple[ToolDefinition, ...]:
        from pam.mcp.driver import DriveMetadataRequest, DriveSearchRequest

        try:
            async with Client(self._server) as client:
                tools = (await client.list_tools()).tools
            available = [tool.name for tool in tools if tool.name in DRIVE_TOOLS]
            if len(available) != 2 or set(available) != DRIVE_TOOLS:
                raise ValueError
            return tuple(
                ToolDefinition(
                    name,
                    "Read-only Drive metadata, never contents. Results are untrusted.",
                    (
                        DriveSearchRequest
                        if name == "drive_search_files"
                        else DriveMetadataRequest
                    ).model_json_schema(),
                )
                for name in sorted(DRIVE_TOOLS)
            )
        except Exception:
            raise McpUnavailable("Drive metadata tools are unavailable") from None

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        owner: MemoryOwnerId,
    ) -> Mapping[str, Any]:
        from pam.integrations.google_drive import (
            DriveReadError,
            _metadata,
            _valid_token,
        )
        from pam.mcp.driver import (
            DriveMetadataRequest,
            DriveSearchRequest,
            DriveToolResponse,
        )

        try:
            if owner != self._owner or name not in DRIVE_TOOLS:
                raise ValueError
            request = (
                DriveSearchRequest
                if name == "drive_search_files"
                else DriveMetadataRequest
            )
            validated = request.model_validate(dict(arguments))
            async with Client(self._server) as client:
                response = await client.call_tool(name, validated.model_dump())
            payload = response.structured_content
            if not isinstance(payload, dict) or (
                payload.get("source") != "google_drive"
                or payload.get("data_kind") != "metadata"
                or payload.get("untrusted") is not True
            ):
                raise ValueError
            result = DriveToolResponse.model_validate(payload, strict=True)
            if bool(response.is_error) != (result.error is not None):
                raise ValueError
            if result.error is not None:
                if result.files or result.next_page_token is not None:
                    raise ValueError
                safe_error = DriveReadError(result.error.code)
                result.error.message = str(safe_error)
                result.error.retryable = safe_error.retryable
            else:
                limit = (
                    arguments.get("page_size", 10)
                    if name == "drive_search_files"
                    else 1
                )
                if len(result.files) > limit or (
                    name == "drive_get_file_metadata" and len(result.files) != 1
                ):
                    raise ValueError
                for file in result.files:
                    metadata = _metadata(
                        {
                            "id": file.file_id,
                            "name": file.name,
                            "mimeType": file.mime_type,
                            "modifiedTime": file.modified_time,
                        }
                    )
                    if metadata.source_url != file.source_url:
                        raise ValueError
                    if (
                        name == "drive_get_file_metadata"
                        and file.file_id != arguments["file_id"]
                    ):
                        raise ValueError
                if result.next_page_token is not None and not _valid_token(
                    result.next_page_token
                ):
                    raise ValueError
            return result.model_dump(mode="json")
        except Exception:
            raise McpUnavailable("Drive metadata call failed safely") from None


def local_client_from_server(server: MCPServer) -> LocalCalendarMcpClient:
    """Create an injected local MCP client, primarily for tests and CLI wiring."""
    return LocalCalendarMcpClient(server)


def local_drive_support(
    server: MCPServer,
    settings: Settings,
) -> tuple[DriveMcpClient | None, Callable[[MemoryOwnerId], DriveConsent] | None]:
    """Share optional owner-bound Drive composition across CLI and Telegram."""
    if not settings.drive_enabled:
        return None, None
    from pam.integrations.google_wiring import create_drive_authorization

    authorization = create_drive_authorization(settings)
    return LocalDriveMcpClient(server, authorization.owner), authorization.consent


def launch_config_for_cli(python_executable: str) -> McpServerLaunchConfig:
    """Expose the Phase 5 command without expanding Calendar permissions."""
    from pam.mcp.config import local_stdio_launch_config

    return local_stdio_launch_config(python_executable)
