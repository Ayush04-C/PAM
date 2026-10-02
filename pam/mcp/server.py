"""Local stdio entry point for PAM's read-only Calendar MCP server."""

from __future__ import annotations

from mcp.server import MCPServer

from pam.application import AvailabilityService
from pam.application.local_calendar import create_local_availability_service
from pam.config import Settings
from pam.integrations.google_wiring import create_google_availability_service
from pam.mcp.calendar import create_calendar_mcp_server


def create_mcp_availability_service(settings: Settings) -> AvailabilityService:
    """Reuse existing backend wiring without exposing it to the MCP tool."""
    if settings.calendar_backend == "google":
        return create_google_availability_service(settings)
    return create_local_availability_service()


def create_mcp_server(settings: Settings | None = None) -> MCPServer:
    """Construct the server with an explicitly selected AvailabilityService."""
    active_settings = settings or Settings()
    return create_calendar_mcp_server(create_mcp_availability_service(active_settings))


def main() -> None:
    """Run the private local server over standard input/output."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
