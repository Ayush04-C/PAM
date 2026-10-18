"""Bounded, provider-neutral in-memory conversation history."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pam.conversation.file_context import FileReferences
from pam.conversation.models import ConversationMessage, DriveBoundary
from pam.memory.models import MemoryOwnerId


class SessionOwnerMismatch(RuntimeError):
    """A caller cannot reuse another owner's conversation state."""


class ConversationStore(Protocol):
    """Minimal storage contract owned by ConversationService."""

    async def load(self, session_id: str) -> tuple[ConversationMessage, ...]:
        """Load portable history for one session."""

    async def load_files(
        self,
        session_id: str,
        owner: MemoryOwnerId,
        boundary: DriveBoundary | None,
        now: datetime,
    ) -> FileReferences | None:
        """Expire references and bind an existing session to its trusted owner."""

    async def commit_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        *,
        drive_boundary: DriveBoundary | None = None,
        file_references: FileReferences | None = None,
        owner: MemoryOwnerId | None = None,
    ) -> None:
        """Atomically append one successful user and assistant exchange."""

    async def clear(self, session_id: str) -> None:
        """Remove only one session's conversational context."""


@dataclass
class _Session:
    history: tuple[ConversationMessage, ...] = ()
    owner: MemoryOwnerId | None = None
    files: FileReferences | None = None


class InMemoryConversationStore:
    """Concurrency-safe LRU session store bounded by message and session counts."""

    def __init__(self, max_history_messages: int = 20, max_sessions: int = 100) -> None:
        if not 1 <= max_history_messages <= 100:
            raise ValueError("max_history_messages must be between 1 and 100")
        if not 1 <= max_sessions <= 1_000:
            raise ValueError("max_sessions must be between 1 and 1000")
        self._max_history_messages = max_history_messages
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = asyncio.Lock()

    async def load(self, session_id: str) -> tuple[ConversationMessage, ...]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
            return session.history if session else ()

    async def load_files(
        self,
        session_id: str,
        owner: MemoryOwnerId,
        boundary: DriveBoundary | None,
        now: datetime,
    ) -> FileReferences | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.owner is not None and session.owner != owner:
                raise SessionOwnerMismatch
            session.owner = owner
            if session.files and not session.files.valid(boundary, now):
                session.files = None
            self._sessions.move_to_end(session_id)
            return session.files

    async def commit_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        *,
        drive_boundary: DriveBoundary | None = None,
        file_references: FileReferences | None = None,
        owner: MemoryOwnerId | None = None,
    ) -> None:
        async with self._lock:
            session = self._sessions.get(session_id, _Session())
            history = session.history + (
                ConversationMessage("user", user_message, drive_boundary),
                ConversationMessage("assistant", assistant_message, drive_boundary),
            )
            session.history = history[-self._max_history_messages :]
            session.files = file_references
            session.owner = owner or session.owner
            if drive_boundary is not None:
                session.owner = drive_boundary.owner
            self._sessions[session_id] = session
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
