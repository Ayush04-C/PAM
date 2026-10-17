"""Local manual conversation CLI for Phase 6."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pydantic import ValidationError
from pydantic_settings import SettingsError

from pam.config import Settings
from pam.conversation.factory import create_model_provider
from pam.conversation.mcp_client import local_client_from_server
from pam.conversation.service import ConversationService
from pam.conversation.store import InMemoryConversationStore
from pam.mcp.server import create_mcp_server
from pam.memory.factory import create_memory_service
from pam.memory.models import MemoryOwnerId


def format_status(settings: Settings) -> str:
    """Describe validated configuration without secrets or connectivity claims."""
    model_configuration = (
        "offline fake provider" if settings.model_provider == "fake" else "present"
    )
    return "\n".join(
        (
            f"Model provider: {settings.model_provider}",
            f"Model configuration: {model_configuration}",
            f"Calendar backend: {settings.calendar_backend}",
            (
                "Drive tools: available through direct MCP diagnostics"
                if settings.drive_enabled
                else "Drive tools: disabled"
            ),
            "Drive model-transfer consent: not collected by CLI",
            f"Drive context limit: {settings.drive_max_context_chars} characters",
            "Live connectivity: not checked",
        )
    )


async def run(settings: Settings | None = None) -> None:
    """Read independent local turns until the user exits."""
    settings = settings if settings is not None else Settings()
    try:
        provider = create_model_provider(settings)
    except ValueError:
        print("Configure PAM_MODEL_PROVIDER and its matching API key to use the CLI.")
        return
    tool_debugger = print if settings.conversation_debug_tool_calls else None
    service = ConversationService(
        provider,
        local_client_from_server(create_mcp_server(settings)),
        conversation_store=InMemoryConversationStore(
            settings.conversation_max_history_messages,
            settings.conversation_max_sessions,
        ),
        memory_service=create_memory_service(settings),
        drive_max_context_chars=settings.drive_max_context_chars,
        on_tool_invoked=(
            (lambda tool_name: tool_debugger(f"tool invoked: {tool_name}"))
            if tool_debugger is not None
            else None
        ),
    )
    while True:
        try:
            message = input("PAM > ").strip()
        except EOFError:
            print()
            return
        if message.lower() in {"exit", "quit"}:
            return
        if message == "/status":
            print(format_status(settings))
            continue
        if message == "/new":
            await service.clear("cli:local")
            print("Started a new conversation.")
            continue
        print(
            await service.respond(
                message,
                session_id="cli:local",
                memory_owner=MemoryOwnerId(settings.memory_cli_owner_id),
            )
        )


def main() -> None:
    """Validate settings before choosing offline diagnostics or conversation."""
    parser = argparse.ArgumentParser(description="PAM local conversation CLI")
    parser.add_argument("--status", action="store_true", help="Show offline status")
    args = parser.parse_args()
    try:
        settings = Settings()
    except (ValidationError, SettingsError, OSError):
        print("Invalid PAM configuration. Check your settings.", file=sys.stderr)
        raise SystemExit(2) from None
    if args.status:
        print(format_status(settings))
        return
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
