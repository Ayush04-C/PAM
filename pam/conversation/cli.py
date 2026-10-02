"""Local manual conversation CLI for Phase 6."""

from __future__ import annotations

import asyncio

from pam.config import Settings
from pam.conversation.gemini import GeminiProvider
from pam.conversation.mcp_client import local_client_from_server
from pam.conversation.service import ConversationService
from pam.mcp.server import create_mcp_server


async def run() -> None:
    """Read independent local turns until the user exits."""
    settings = Settings()
    if settings.model_provider != "gemini" or settings.gemini_api_key is None:
        print("Set PAM_MODEL_PROVIDER=gemini and PAM_GEMINI_API_KEY to use the CLI.")
        return
    provider = GeminiProvider(
        settings.gemini_api_key.get_secret_value(), settings.gemini_model
    )
    tool_debugger = print if settings.conversation_debug_tool_calls else None
    service = ConversationService(
        provider,
        local_client_from_server(create_mcp_server(settings)),
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
        print(await service.respond(message))


def main() -> None:
    """Run the asynchronous CLI."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
