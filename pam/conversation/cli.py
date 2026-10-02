"""Local manual conversation CLI for Phase 6."""

from __future__ import annotations

import asyncio

from pam.config import Settings
from pam.conversation.factory import create_model_provider
from pam.conversation.mcp_client import local_client_from_server
from pam.conversation.service import ConversationService
from pam.conversation.store import InMemoryConversationStore
from pam.mcp.server import create_mcp_server
from pam.memory.factory import create_memory_service
from pam.memory.models import MemoryOwnerId


async def run() -> None:
    """Read independent local turns until the user exits."""
    settings = Settings()
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
    """Run the asynchronous CLI."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
