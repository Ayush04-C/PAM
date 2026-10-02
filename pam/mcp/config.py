"""Typed local stdio launch configuration for a future MCP client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class McpServerLaunchConfig:
    """Describe the local process a future agent can launch."""

    command: str
    args: tuple[str, ...]
    transport: Literal["stdio"] = "stdio"


def local_stdio_launch_config(python_executable: str) -> McpServerLaunchConfig:
    """Return the private local stdio command for PAM's single MCP server."""
    return McpServerLaunchConfig(
        command=python_executable,
        args=("-m", "pam.mcp.server"),
    )
