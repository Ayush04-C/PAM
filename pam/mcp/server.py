"""Private stdio entry point for PAM's shared read-only MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import Client
from mcp.server import MCPServer
from pydantic import ValidationError
from pydantic_settings import SettingsError

from pam.application import AvailabilityService
from pam.application.local_calendar import create_local_availability_service
from pam.config import Settings
from pam.integrations.google_drive import GoogleDriveReader
from pam.integrations.google_wiring import (
    create_drive_authorization,
    create_google_availability_service,
)
from pam.mcp.calendar import create_calendar_tool
from pam.mcp.driver import create_drive_tools


def create_mcp_availability_service(settings: Settings) -> AvailabilityService:
    """Reuse existing backend wiring without exposing it to the MCP tool."""
    if settings.calendar_backend == "google":
        return create_google_availability_service(settings)
    return create_local_availability_service()


def create_mcp_server(settings: Settings | None = None) -> MCPServer:
    """Construct the server with an explicitly selected AvailabilityService."""
    active_settings = settings or Settings()
    tools = [create_calendar_tool(create_mcp_availability_service(active_settings))]
    if active_settings.drive_enabled:
        tools.extend(
            create_drive_tools(
                GoogleDriveReader(create_drive_authorization(active_settings)),
                content_enabled=active_settings.drive_content_enabled,
            )
        )
    return MCPServer(
        name="PAM",
        description="Private read-only Calendar and Drive tools.",
        tools=tools,
    )


async def _diagnostic(
    server: MCPServer,
    tool_name: str | None,
    arguments: dict[str, object],
) -> int:
    """Exercise the MCP SDK directly without creating a model or memory client."""
    try:
        async with Client(server) as client:
            if tool_name is None:
                discovered = await client.list_tools()
                print(json.dumps([tool.name for tool in discovered.tools]))
                return 0
            result = await client.call_tool(tool_name, arguments)
            payload = result.structured_content or {
                "error": "MCP tool input or invocation failed"
            }
            print(json.dumps(payload))
            return 1 if result.is_error else 0
    except Exception:
        print("MCP diagnostics unavailable.", file=sys.stderr)
        return 1


def main() -> None:
    """Run stdio normally, or an explicit offline-list/direct-tool diagnostic."""
    parser = argparse.ArgumentParser(description="PAM private shared MCP server")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-tools", action="store_true")
    mode.add_argument(
        "--call-tool",
        choices=[
            "get_weekly_availability",
            "drive_search_files",
            "drive_get_file_metadata",
        ],
        help="Read a JSON argument object from stdin and invoke one tool directly",
    )
    args = parser.parse_args()
    arguments: dict[str, object] = {}
    if args.call_tool is not None:
        raw = sys.stdin.read(8193)
        try:
            parsed = json.loads(raw) if len(raw) <= 8192 else None
        except (ValueError, RecursionError):
            parsed = None
        if not isinstance(parsed, dict):
            parser.error(
                "stdin must contain a JSON argument object of at most 8192 characters"
            )
        arguments = parsed
    try:
        server = create_mcp_server()
    except (ValidationError, SettingsError, OSError, ValueError):
        print("Invalid PAM configuration. Check your settings.", file=sys.stderr)
        raise SystemExit(2) from None
    if args.list_tools or args.call_tool is not None:
        raise SystemExit(asyncio.run(_diagnostic(server, args.call_tool, arguments)))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
