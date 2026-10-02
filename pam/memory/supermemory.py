"""Supermemory implementation hidden behind PAM's memory boundary."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from supermemory import AsyncSupermemory

from pam.memory.models import MemoryOwnerId, RecalledMemory
from pam.memory.service import MemoryUnavailable

logger = logging.getLogger("pam.memory")


class SupermemoryMemoryService:
    """Bounded, owner-isolated access to Supermemory's managed memory engine."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.supermemory.ai",
        max_recalled_items: int = 5,
        max_content_chars: int = 500,
        client: Any | None = None,
    ) -> None:
        if not 1 <= max_recalled_items <= 20:
            raise ValueError("max_recalled_items must be between 1 and 20")
        if not 100 <= max_content_chars <= 4_000:
            raise ValueError("max_content_chars must be between 100 and 4000")
        self._client: Any = client or AsyncSupermemory(
            api_key=api_key, base_url=base_url, timeout=15.0, max_retries=1
        )
        self._max_recalled_items = max_recalled_items
        self._max_content_chars = max_content_chars

    async def recall(
        self, owner: MemoryOwnerId, query: str
    ) -> tuple[RecalledMemory, ...]:
        try:
            response = await self._client.search.memories(
                q=query,
                container_tag=self._container_tag(owner),
                search_mode="hybrid",
                include={"documents": True},
                limit=self._max_recalled_items,
            )
            memories = tuple(
                RecalledMemory(content)
                for content in self._contents_from_response(response)
            )
        except Exception as error:
            raise MemoryUnavailable("long-term memory is unavailable") from error
        logger.info(
            "memory recall completed",
            extra={
                "backend": "supermemory",
                "owner": self._owner_hash(owner),
                "count": len(memories),
            },
        )
        return memories

    async def ingest_turn(
        self,
        owner: MemoryOwnerId,
        messages: tuple[tuple[str, str], ...],
        conversation_id: str,
    ) -> None:
        try:
            await self._client.post(
                "/v4/conversations",
                cast_to=dict,
                body={
                    "conversationId": self._conversation_document_id(
                        owner, conversation_id
                    ),
                    "messages": [
                        {"role": role, "content": content} for role, content in messages
                    ],
                    "containerTags": [self._container_tag(owner)],
                    "metadata": {"application": "pam", "source": "conversation"},
                },
            )
        except Exception as error:
            raise MemoryUnavailable("long-term memory is unavailable") from error
        logger.info(
            "memory ingestion completed",
            extra={
                "backend": "supermemory",
                "owner": self._owner_hash(owner),
                "source": "conversation",
            },
        )

    async def remember(self, owner: MemoryOwnerId, content: str) -> None:
        self._require_specific_content(content)
        await self._add(owner, content, "explicit-memory")

    async def forget(self, owner: MemoryOwnerId, query: str) -> None:
        self._require_specific_content(query)
        try:
            await self._client.memories.forget(
                container_tag=self._container_tag(owner),
                content=query.strip(),
                reason="explicit user request",
            )
        except Exception as error:
            raise MemoryUnavailable("long-term memory is unavailable") from error
        logger.info(
            "memory forget completed",
            extra={"backend": "supermemory", "owner": self._owner_hash(owner)},
        )

    async def _add(
        self,
        owner: MemoryOwnerId,
        content: str,
        source: str,
    ) -> None:
        if source != "explicit-memory":
            raise ValueError("only explicit memories may use document ingestion")
        entity_context = (
            "The user explicitly asked PAM to persist this durable preference or fact. "
            "Extract it as recallable user memory."
        )
        try:
            await self._client.add(
                content=content,
                container_tag=self._container_tag(owner),
                metadata={"application": "pam", "source": source},
                task_type="memory",
                dreaming="instant",
                entity_context=entity_context,
            )
        except Exception as error:
            raise MemoryUnavailable("long-term memory is unavailable") from error
        logger.info(
            "memory ingestion completed",
            extra={
                "backend": "supermemory",
                "owner": self._owner_hash(owner),
                "source": source,
            },
        )

    def _contents_from_response(self, response: object) -> tuple[str, ...]:
        results = getattr(response, "results", None)
        if not isinstance(results, list):
            raise ValueError("invalid Supermemory response")
        contents: list[str] = []
        for result in results[: self._max_recalled_items]:
            content = self._content_from_result(result)
            if isinstance(content, str) and content.strip():
                contents.append(content.strip()[: self._max_content_chars])
        return tuple(contents)

    @staticmethod
    def _content_from_result(result: object) -> str | None:
        """Map current SDK memory results and trusted explicit-document chunks."""
        memory = getattr(result, "memory", None)
        if isinstance(memory, str) and memory.strip():
            return memory
        chunk = getattr(result, "chunk", None)
        if isinstance(chunk, str) and chunk.strip():
            documents = getattr(result, "documents", None)
            if isinstance(documents, list) and any(
                isinstance(getattr(document, "metadata", None), dict)
                and document.metadata.get("source") == "explicit-memory"
                for document in documents
            ):
                return chunk
        content = getattr(result, "content", None)
        return content if isinstance(content, str) and content.strip() else None

    @staticmethod
    def _require_specific_content(content: str) -> None:
        normalized = content.strip()
        if len(normalized) < 3 or normalized.casefold() in {
            "all",
            "everything",
            "all memories",
            "everything you know",
        }:
            raise ValueError("please specify the memory to change")

    @staticmethod
    def _owner_hash(owner: MemoryOwnerId) -> str:
        return hashlib.sha256(owner.value.encode()).hexdigest()[:32]

    @classmethod
    def _container_tag(cls, owner: MemoryOwnerId) -> str:
        return f"pam-user-{cls._owner_hash(owner)}"

    @classmethod
    def _conversation_document_id(cls, owner: MemoryOwnerId, session_id: str) -> str:
        digest = hashlib.sha256(f"{owner.value}:{session_id}".encode()).hexdigest()[:32]
        return f"pam-conversation-{digest}"
