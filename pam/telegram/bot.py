"""Local long-polling runner for PAM's private text-only Telegram bot."""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    ExtBot,
    JobQueue,
    MessageHandler,
    filters,
)

from pam.config import Settings
from pam.conversation.factory import create_model_provider
from pam.conversation.mcp_client import local_client_from_server
from pam.conversation.service import ConversationService
from pam.conversation.store import InMemoryConversationStore
from pam.logging import configure_logging
from pam.mcp.server import create_mcp_server
from pam.telegram.adapter import Reply, TelegramAdapter

logger = logging.getLogger("pam.telegram")

type TelegramContext = CallbackContext[
    ExtBot[None], dict[Any, Any], dict[Any, Any], dict[Any, Any]
]
type TelegramApplication = Application[
    ExtBot[None],
    TelegramContext,
    dict[Any, Any],
    dict[Any, Any],
    dict[Any, Any],
    JobQueue[TelegramContext],
]


def build_conversation_service(settings: Settings) -> ConversationService:
    """Build application-lifetime conversation dependencies once for polling."""
    provider = create_model_provider(settings)
    return ConversationService(
        provider,
        local_client_from_server(create_mcp_server(settings)),
        conversation_store=InMemoryConversationStore(
            settings.conversation_max_history_messages,
            settings.conversation_max_sessions,
        ),
        on_tool_invoked=(
            lambda tool_name: (
                logger.info("tool invoked", extra={"tool_name": tool_name})
                if settings.conversation_debug_tool_calls
                else None
            )
        ),
    )


class TelegramUpdateHandler:
    """Translate python-telegram-bot updates into the thin transport adapter."""

    def __init__(self, adapter: TelegramAdapter) -> None:
        self._adapter = adapter

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        await self._adapter.handle_text(
            user_id=_user_id(update),
            chat_type=_chat_type(update),
            text="/start",
            reply=_reply_for(update),
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        await self._adapter.handle_text(
            user_id=_user_id(update),
            chat_type=_chat_type(update),
            text="/help",
            reply=_reply_for(update),
        )

    async def new(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clear one authorized private conversation without model execution."""
        del context
        await self._adapter.handle_text(
            user_id=_user_id(update),
            chat_type=_chat_type(update),
            text="/new",
            reply=_reply_for(update),
        )

    async def text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        await self._adapter.handle_text(
            user_id=_user_id(update),
            chat_type=_chat_type(update),
            text=message.text if message is not None else None,
            reply=_reply_for(update),
        )

    async def unsupported(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        await self._adapter.handle_unsupported(
            user_id=_user_id(update),
            chat_type=_chat_type(update),
            reply=_reply_for(update),
        )


def build_telegram_application(
    settings: Settings, conversation_service: ConversationService
) -> TelegramApplication:
    """Construct polling handlers with an injected existing conversation service."""
    if settings.telegram_bot_token is None:
        raise ValueError("Telegram bot token is required")
    adapter = TelegramAdapter(conversation_service, settings.telegram_allowed_user_ids)
    handler = TelegramUpdateHandler(adapter)
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token.get_secret_value())
        .build()
    )
    application.add_handler(CommandHandler("start", handler.start))
    application.add_handler(CommandHandler("help", handler.help))
    application.add_handler(CommandHandler("new", handler.new))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handler.text)
    )
    application.add_handler(MessageHandler(~filters.TEXT, handler.unsupported))
    return application


def _user_id(update: Update) -> int | None:
    user = update.effective_user
    return user.id if user is not None else None


def _chat_type(update: Update) -> str | None:
    chat = update.effective_chat
    return chat.type if chat is not None else None


def _reply_for(update: Update) -> Reply:
    message = update.effective_message

    async def reply(text: str) -> None:
        if message is None:
            logger.warning("unable to reply to malformed Telegram update")
            return
        try:
            await message.reply_text(text)
        except Exception:
            logger.warning(
                "Telegram reply failed", extra={"update_id": update.update_id}
            )

    return reply


def main() -> None:
    """Start local long polling only when explicitly enabled in configuration."""
    configure_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    settings = Settings()
    if not settings.telegram_enabled:
        raise ValueError("Set PAM_TELEGRAM_ENABLED=true to start Telegram polling")
    application = build_telegram_application(
        settings, build_conversation_service(settings)
    )
    try:
        application.run_polling()
    except InvalidToken:
        raise SystemExit(
            "Telegram bot token was rejected. Regenerate it through BotFather and "
            "store the complete replacement token in .env."
        ) from None
    except TelegramError:
        logger.error("Telegram polling stopped")
        raise SystemExit("Telegram polling stopped. Please try again.") from None


if __name__ == "__main__":
    main()
