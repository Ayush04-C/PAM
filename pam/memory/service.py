"""PAM-owned interface for long-term memory infrastructure."""

from __future__ import annotations

from typing import Protocol

from pam.memory.models import MemoryOwnerId, RecalledMemory


class MemoryUnavailable(RuntimeError):
    """Durable-memory infrastructure could not complete an operation safely."""


class MemoryService(Protocol):
    """Provider-neutral durable memory boundary owned by PAM."""

    async def recall(
        self, owner: MemoryOwnerId, query: str
    ) -> tuple[RecalledMemory, ...]: ...

    async def ingest_turn(
        self,
        owner: MemoryOwnerId,
        messages: tuple[tuple[str, str], ...],
        conversation_id: str,
    ) -> None: ...

    async def remember(self, owner: MemoryOwnerId, content: str) -> None: ...

    async def forget(self, owner: MemoryOwnerId, query: str) -> None: ...


class DisabledMemoryService:
    """No-op backend keeping durable memory optional for local/offline use."""

    async def recall(
        self, owner: MemoryOwnerId, query: str
    ) -> tuple[RecalledMemory, ...]:
        del owner, query
        return ()

    async def ingest_turn(
        self,
        owner: MemoryOwnerId,
        messages: tuple[tuple[str, str], ...],
        conversation_id: str,
    ) -> None:
        del owner, messages, conversation_id

    async def remember(self, owner: MemoryOwnerId, content: str) -> None:
        del owner, content
        raise MemoryUnavailable("long-term memory is disabled")

    async def forget(self, owner: MemoryOwnerId, query: str) -> None:
        del owner, query
        raise MemoryUnavailable("long-term memory is disabled")
