"""Configured provider selection shared by local conversation transports."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pam.config import Settings
from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.gemini import GeminiProvider
from pam.conversation.provider import ModelProvider

if TYPE_CHECKING:
    from pam.conversation.service import ConversationService


def configured_model_destination(settings: Settings) -> str | None:
    """Identify the configured transfer target without constructing SDK clients."""
    if settings.model_provider == "bharatcode":
        return (
            f"bharatcode:{settings.bharatcode_base_url.rstrip('/')}"
            f"|{settings.bharatcode_model}"
        )
    if settings.model_provider == "gemini":
        return (
            f"gemini:https://generativelanguage.googleapis.com|{settings.gemini_model}"
        )
    return None


def create_model_provider(settings: Settings) -> ModelProvider:
    """Construct only the explicitly selected provider; never auto-fallback."""
    if settings.model_provider == "bharatcode":
        if settings.bharatcode_api_key is None:
            raise ValueError("PAM_BHARATCODE_API_KEY is required")
        return BharatCodeProvider(
            settings.bharatcode_api_key.get_secret_value(),
            settings.bharatcode_model,
            settings.bharatcode_base_url,
        )
    if settings.model_provider == "gemini":
        if settings.gemini_api_key is None:
            raise ValueError("PAM_GEMINI_API_KEY is required")
        return GeminiProvider(
            settings.gemini_api_key.get_secret_value(), settings.gemini_model
        )
    raise ValueError("A hosted model provider is required for this command")


def create_conversation_service(
    settings: Settings,
    *,
    on_tool_invoked: Callable[[str], None] | None = None,
) -> ConversationService:
    """Build one shared set of dependencies for CLI and Telegram."""
    # Local imports avoid the Google wiring -> destination factory import cycle.
    from pam.conversation.mcp_client import (
        local_client_from_server,
        local_drive_support,
    )
    from pam.conversation.service import ConversationService
    from pam.conversation.store import InMemoryConversationStore
    from pam.mcp.server import create_mcp_server
    from pam.memory.factory import create_memory_service

    provider = create_model_provider(settings)
    server = create_mcp_server(settings)
    drive_mcp, consent_loader = local_drive_support(server, settings)
    return ConversationService(
        provider,
        local_client_from_server(server),
        drive_mcp=drive_mcp,
        drive_consent_loader=consent_loader,
        conversation_store=InMemoryConversationStore(
            settings.conversation_max_history_messages,
            settings.conversation_max_sessions,
        ),
        memory_service=create_memory_service(settings),
        drive_max_context_chars=settings.drive_max_context_chars,
        drive_content_enabled=settings.drive_content_enabled,
        on_tool_invoked=on_tool_invoked,
    )
