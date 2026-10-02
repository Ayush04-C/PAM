"""Offline tests for PAM's thin, private, text-only Telegram transport."""

from __future__ import annotations

from datetime import datetime

import pytest

from pam.application import AvailabilityService, FakeCalendarReader
from pam.config import Settings
from pam.conversation.mcp_client import local_client_from_server
from pam.conversation.models import ModelDecision, ToolCall
from pam.conversation.provider import ScriptedModelProvider
from pam.conversation.service import ConversationService
from pam.domain import DISPLAY_TIMEZONE, CalendarEvent
from pam.mcp.calendar import create_calendar_mcp_server
from pam.telegram import bot
from pam.telegram.adapter import (
    ACCESS_DENIED_MESSAGE,
    HELP_MESSAGE,
    MAX_INCOMING_TEXT_LENGTH,
    MAX_OUTGOING_TEXT_LENGTH,
    PRIVATE_CHAT_MESSAGE,
    SERVICE_FAILURE_MESSAGE,
    START_MESSAGE,
    TEXT_ONLY_MESSAGE,
    TOO_LONG_MESSAGE,
    TelegramAdapter,
    split_telegram_text,
)


class RecordingConversation:
    def __init__(self, response: str = "You are free.") -> None:
        self.response = response
        self.messages: list[str] = []
        self.session_ids: list[str] = []
        self.cleared_session_ids: list[str] = []
        self.fail = False

    async def respond(self, user_message: str, *, session_id: str) -> str:
        self.messages.append(user_message)
        self.session_ids.append(session_id)
        if self.fail:
            raise RuntimeError("TELEGRAM_TOKEN_DO_NOT_LEAK")
        return self.response

    async def clear(self, session_id: str) -> None:
        self.cleared_session_ids.append(session_id)


async def replies_for(
    adapter: TelegramAdapter,
    *,
    user_id: int | None = 7,
    chat_type: str | None = "private",
    text: str | None = "Hello",
) -> list[str]:
    replies: list[str] = []

    async def reply(message: str) -> None:
        replies.append(message)

    await adapter.handle_text(
        user_id=user_id, chat_type=chat_type, text=text, reply=reply
    )
    return replies


@pytest.mark.asyncio
async def test_start_and_help_are_static_and_do_not_call_conversation() -> None:
    conversation = RecordingConversation()
    adapter = TelegramAdapter(conversation, (7,))

    assert await replies_for(adapter, text="/start") == [START_MESSAGE]
    assert await replies_for(adapter, text="/help") == [HELP_MESSAGE]
    assert conversation.messages == []


@pytest.mark.asyncio
async def test_new_clears_only_authorized_private_session_without_model_call() -> None:
    conversation = RecordingConversation()
    adapter = TelegramAdapter(conversation, (7,))

    assert await replies_for(adapter, text="/new") == ["Started a new conversation."]
    assert conversation.cleared_session_ids == ["telegram:7"]
    assert conversation.messages == []
    assert await replies_for(adapter, user_id=8, text="/new") == [ACCESS_DENIED_MESSAGE]
    assert conversation.cleared_session_ids == ["telegram:7"]


@pytest.mark.asyncio
async def test_authorized_private_text_preserves_exact_input_and_response() -> None:
    conversation = RecordingConversation("Your availability is clear.")
    adapter = TelegramAdapter(conversation, (7,))

    assert await replies_for(adapter, text=" How busy am I today? ") == [
        "Your availability is clear."
    ]
    assert conversation.messages == [" How busy am I today? "]
    assert conversation.session_ids == ["telegram:7"]


@pytest.mark.asyncio
async def test_unauthorized_group_and_missing_sender_cannot_invoke_conversation() -> (
    None
):
    conversation = RecordingConversation()
    adapter = TelegramAdapter(conversation, (7,))

    assert await replies_for(adapter, user_id=8) == [ACCESS_DENIED_MESSAGE]
    assert await replies_for(adapter, chat_type="group") == [PRIVATE_CHAT_MESSAGE]
    assert await replies_for(adapter, user_id=None) == [ACCESS_DENIED_MESSAGE]
    assert conversation.messages == []


@pytest.mark.asyncio
async def test_missing_text_unsupported_and_overlong_input_are_safe() -> None:
    conversation = RecordingConversation()
    adapter = TelegramAdapter(conversation, (7,))
    replies: list[str] = []

    async def reply(message: str) -> None:
        replies.append(message)

    assert await replies_for(adapter, text=None) == [TEXT_ONLY_MESSAGE]
    await adapter.handle_unsupported(
        user_id=7,
        chat_type="private",
        reply=reply,
    )
    assert replies == [TEXT_ONLY_MESSAGE]
    assert await replies_for(adapter, text="x" * (MAX_INCOMING_TEXT_LENGTH + 1)) == [
        TOO_LONG_MESSAGE
    ]
    assert conversation.messages == []


@pytest.mark.asyncio
async def test_service_failure_does_not_leak_token_or_private_data() -> None:
    conversation = RecordingConversation()
    conversation.fail = True
    adapter = TelegramAdapter(conversation, (7,))

    replies = await replies_for(adapter)

    assert replies == [SERVICE_FAILURE_MESSAGE]
    assert "TELEGRAM_TOKEN_DO_NOT_LEAK" not in " ".join(replies)


def test_long_plain_text_is_split_at_safe_boundaries() -> None:
    text = ("word " * 1_000).strip()
    chunks = split_telegram_text(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_OUTGOING_TEXT_LENGTH for chunk in chunks)
    assert " ".join(chunks) == text


def test_telegram_enabled_requires_numeric_allowlist_and_token() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        Settings(_env_file=None, telegram_enabled=True, model_provider="fake")
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        Settings(
            _env_file=None,
            telegram_enabled=True,
            model_provider="fake",
            telegram_bot_token="telegram-token-do-not-log",
        )
    settings = Settings(
        _env_file=None,
        telegram_enabled=True,
        model_provider="fake",
        telegram_bot_token="telegram-token-do-not-log",
        telegram_allowed_user_ids="7, 8",
    )
    assert settings.telegram_allowed_user_ids == (7, 8)
    numeric_setting = Settings(
        _env_file=None,
        telegram_enabled=True,
        model_provider="fake",
        telegram_bot_token="telegram-token-do-not-log",
        telegram_allowed_user_ids=7,
    )
    assert numeric_setting.telegram_allowed_user_ids == (7,)


@pytest.mark.asyncio
async def test_real_conversation_and_real_phase_five_mcp_integrate_offline() -> None:
    event = CalendarEvent(
        "Lecture",
        datetime(2026, 10, 5, 10, tzinfo=DISPLAY_TIMEZONE),
        datetime(2026, 10, 5, 12, tzinfo=DISPLAY_TIMEZONE),
    )
    request = {
        "start_date": "2026-10-05",
        "end_date": "2026-10-05",
        "timezone": "Asia/Kolkata",
    }
    provider = ScriptedModelProvider(
        [
            ModelDecision(tool_call=ToolCall("get_weekly_availability", request)),
            ModelDecision(text="You are busy for 2 hours on Monday."),
        ]
    )
    service = ConversationService(
        provider,
        local_client_from_server(
            create_calendar_mcp_server(
                AvailabilityService(FakeCalendarReader((event,)))
            )
        ),
        clock=lambda: datetime(2026, 10, 2, tzinfo=DISPLAY_TIMEZONE),
    )
    adapter = TelegramAdapter(service, (7,))

    assert await replies_for(adapter, text="How busy am I Monday?") == [
        "You are busy for 2 hours on Monday."
    ]
    assert "2 hours busy" in provider.tool_results[0].result["availability"]


def test_invalid_telegram_token_exits_without_echoing_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "telegram-token-do-not-echo"

    class FakeApplication:
        def run_polling(self) -> None:
            from telegram.error import InvalidToken

            raise InvalidToken(token)

    settings = Settings(
        _env_file=None,
        telegram_enabled=True,
        telegram_bot_token=token,
        telegram_allowed_user_ids=(7,),
        model_provider="gemini",
        gemini_api_key="gemini-key",
    )
    monkeypatch.setattr(bot, "Settings", lambda: settings)
    monkeypatch.setattr(bot, "build_conversation_service", lambda _: object())
    monkeypatch.setattr(bot, "build_telegram_application", lambda *_: FakeApplication())

    with pytest.raises(SystemExit) as error:
        bot.main()

    assert token not in str(error.value)
    assert "rejected" in str(error.value)
