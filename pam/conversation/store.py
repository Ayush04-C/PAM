"""Bounded, provider-neutral in-memory conversation history."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Protocol

from pam.conversation.models import ConversationMessage


class ConversationStore(Protocol):
    """Minimal storage contract owned by ConversationService."""

    async def load(self, session_id: str) -> tuple[ConversationMessage, ...]:
        """Load portable history for one session."""

    async def commit_turn(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None:
        """Atomically append one successful user and assistant exchange."""

    async def clear(self, session_id: str) -> None:
        """Remove only one session's conversational context."""


class InMemoryConversationStore:
    """Concurrency-safe LRU session store bounded by message and session counts."""

    def __init__(self, max_history_messages: int = 20, max_sessions: int = 100) -> None:
        if not 1 <= max_history_messages <= 100:
            raise ValueError("max_history_messages must be between 1 and 100")
        if not 1 <= max_sessions <= 1_000:
            raise ValueError("max_sessions must be between 1 and 1000")
        self._max_history_messages = max_history_messages
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, tuple[ConversationMessage, ...]] = (
            OrderedDict()
        )
        self._lock = asyncio.Lock()

    async def load(self, session_id: str) -> tuple[ConversationMessage, ...]:
        async with self._lock:
            history = self._sessions.get(session_id, ())
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
            return history

    async def commit_turn(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None:
        async with self._lock:
            history = self._sessions.get(session_id, ()) + (
                ConversationMessage("user", user_message),
                ConversationMessage("assistant", assistant_message),
            )
            self._sessions[session_id] = history[-self._max_history_messages :]
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
