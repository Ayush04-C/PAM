"""Telegram transport policy with no Calendar, MCP, or Gemini implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from pam.memory.models import MemoryOwnerId

MAX_INCOMING_TEXT_LENGTH = 4_096
MAX_OUTGOING_TEXT_LENGTH = 4_096
START_MESSAGE = (
    "Hi, I'm PAM. I can answer availability questions using your Google Calendar. "
    "Calendar access is currently read-only."
)
HELP_MESSAGE = (
    "Try: How busy am I today? What does tomorrow look like? "
    "Am I free this weekend? How busy am I next Monday? Calendar access is read-only."
)
ACCESS_DENIED_MESSAGE = "Access denied."
PRIVATE_CHAT_MESSAGE = "PAM is available only in private chats."
TEXT_ONLY_MESSAGE = "For now, please send me a text message."
TOO_LONG_MESSAGE = "Please send a shorter message."
SERVICE_FAILURE_MESSAGE = "PAM is unavailable right now. Please try again."

Reply = Callable[[str], Awaitable[None]]


class ConversationResponder(Protocol):
    """The sole conversation dependency needed by the Telegram transport."""

    async def respond(
        self, user_message: str, *, session_id: str, memory_owner: MemoryOwnerId
    ) -> str:
        """Produce a safe single-turn reply."""

    async def clear(self, session_id: str) -> None:
        """Clear one explicitly selected session."""


class TelegramAdapter:
    """Authorize and transport private Telegram text to ConversationService."""

    def __init__(
        self,
        conversation_service: ConversationResponder,
        allowed_user_ids: tuple[int, ...],
    ) -> None:
        self._conversation_service = conversation_service
        self._allowed_user_ids = frozenset(allowed_user_ids)

    async def handle_text(
        self,
        *,
        user_id: int | None,
        chat_type: str | None,
        text: str | None,
        reply: Reply,
    ) -> None:
        """Apply transport policy before forwarding only authorized private text."""
        if not self._is_authorized_private_user(user_id, chat_type):
            await reply(self._denial_for(user_id, chat_type))
            return
        if text is None:
            await reply(TEXT_ONLY_MESSAGE)
            return
        if len(text) > MAX_INCOMING_TEXT_LENGTH:
            await reply(TOO_LONG_MESSAGE)
            return
        if text == "/start":
            await reply(START_MESSAGE)
            return
        if text == "/help":
            await reply(HELP_MESSAGE)
            return
        session_id = f"telegram:{user_id}"
        if text == "/new":
            await self._conversation_service.clear(session_id)
            await reply("Started a new conversation.")
            return
        try:
            response = await self._conversation_service.respond(
                text,
                session_id=session_id,
                memory_owner=MemoryOwnerId(f"telegram:{user_id}"),
            )
        except Exception:
            await reply(SERVICE_FAILURE_MESSAGE)
            return
        for chunk in split_telegram_text(response):
            await reply(chunk)

    async def handle_unsupported(
        self, *, user_id: int | None, chat_type: str | None, reply: Reply
    ) -> None:
        """Return the deterministic text-only message after access checks."""
        if not self._is_authorized_private_user(user_id, chat_type):
            await reply(self._denial_for(user_id, chat_type))
            return
        await reply(TEXT_ONLY_MESSAGE)

    def _is_authorized_private_user(
        self, user_id: int | None, chat_type: str | None
    ) -> bool:
        return (
            user_id is not None
            and chat_type == "private"
            and user_id in self._allowed_user_ids
        )

    @staticmethod
    def _denial_for(user_id: int | None, chat_type: str | None) -> str:
        if chat_type != "private":
            return PRIVATE_CHAT_MESSAGE
        if user_id is None:
            return ACCESS_DENIED_MESSAGE
        return ACCESS_DENIED_MESSAGE


def split_telegram_text(text: str) -> tuple[str, ...]:
    """Split long plain-text output at natural boundaries without data loss."""
    if not text:
        return ("I don't have a response yet.",)
    chunks: list[str] = []
    remaining = text
    while len(remaining) > MAX_OUTGOING_TEXT_LENGTH:
        boundary = max(
            remaining.rfind("\n", 0, MAX_OUTGOING_TEXT_LENGTH + 1),
            remaining.rfind(" ", 0, MAX_OUTGOING_TEXT_LENGTH + 1),
        )
        if boundary <= 0:
            boundary = MAX_OUTGOING_TEXT_LENGTH
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
        if remaining.startswith((" ", "\n")):
            remaining = remaining[1:]
    chunks.append(remaining)
    return tuple(chunks)
