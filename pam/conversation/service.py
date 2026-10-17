"""Bounded orchestration of an untrusted model and approved MCP tool."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime

from pam.conversation.mcp_client import CalendarMcpClient, McpUnavailable
from pam.conversation.models import (
    DriveBoundary,
    DriveConsent,
    DriveConsentRequired,
    DriveContext,
    DriveDataKind,
    ModelTurn,
    ToolDefinition,
    ToolResult,
)
from pam.conversation.provider import ModelProvider, ModelUnavailable
from pam.conversation.store import ConversationStore, InMemoryConversationStore
from pam.conversation.system_prompt import build_system_instruction
from pam.domain import DISPLAY_TIMEZONE
from pam.memory.models import MemoryOwnerId
from pam.memory.service import DisabledMemoryService, MemoryService, MemoryUnavailable

_ALLOWED_TOOL = "get_weekly_availability"
_TOOL_FAILURE = "I couldn't retrieve calendar availability. Please try again."
_MODEL_FAILURE = "PAM's conversation service is unavailable. Please try again."
_READ_ONLY = "Calendar access is currently read-only; I can't change events."
_MEMORY_SAVE_FAILURE = "I couldn't save that memory. Please try again."
_MEMORY_FORGET_FAILURE = "I couldn't forget that memory. Please try again."
_CONSENT_FAILURE = (
    "Drive access or model-transfer consent is missing or no longer matches. "
    "Reconnect consent, or use /new to start without the previous Drive context."
)


class ConversationService:
    """Run one model-led turn, permitting only Calendar availability through MCP."""

    def __init__(
        self,
        provider: ModelProvider,
        calendar_mcp: CalendarMcpClient,
        *,
        clock: Callable[[], datetime] | None = None,
        max_tool_rounds: int = 2,
        on_tool_invoked: Callable[[str], None] | None = None,
        conversation_store: ConversationStore | None = None,
        memory_service: MemoryService | None = None,
        drive_max_context_chars: int = 20_000,
    ) -> None:
        if not 1 <= drive_max_context_chars <= 20_000:
            raise ValueError("Drive context limit must be between 1 and 20000")
        self._drive_max_context_chars = drive_max_context_chars
        self._provider = provider
        self._calendar_mcp = calendar_mcp
        self._clock = clock or (lambda: datetime.now(DISPLAY_TIMEZONE))
        self._max_tool_rounds = max_tool_rounds
        self._on_tool_invoked = on_tool_invoked
        self._conversation_store = conversation_store or InMemoryConversationStore()
        self._memory_service = memory_service or DisabledMemoryService()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._memory_conversation_ids: dict[str, str] = {}

    async def respond(
        self,
        user_message: str,
        *,
        session_id: str = "default",
        memory_owner: MemoryOwnerId | None = None,
        drive_context: DriveContext | None = None,
        drive_consent: DriveConsent | None = None,
    ) -> str:
        """Return a safe text answer without exposing provider or MCP internals."""
        if not user_message.strip():
            return "Please ask a Calendar availability question."
        if (
            drive_context is not None
            and len(drive_context.text) > self._drive_max_context_chars
        ):
            return "Drive context exceeds the configured limit. Supply less text."
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            owner = memory_owner or MemoryOwnerId(f"session:{session_id}")
            action = self._memory_action(user_message)
            if action is not None:
                if drive_context is not None:
                    return "Please supply a specific memory without Drive context."
                return await self._perform_memory_action(owner, *action)
            return await self._respond_in_session(
                user_message, session_id, owner, drive_context, drive_consent
            )

    async def clear(self, session_id: str) -> None:
        """Clear one session explicitly without contacting a provider or Calendar."""
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self._conversation_store.clear(session_id)
            self._memory_conversation_ids.pop(session_id, None)

    async def _respond_in_session(
        self,
        user_message: str,
        session_id: str,
        owner: MemoryOwnerId,
        drive_context: DriveContext | None,
        drive_consent: DriveConsent | None,
    ) -> str:
        """Process and atomically commit one successful conversation turn."""
        now = self._clock()
        history = await self._conversation_store.load(session_id)
        boundaries = [m.drive_boundary for m in history if m.drive_boundary is not None]
        boundary = None
        if drive_context is not None or boundaries:
            destination = getattr(self._provider, "data_destination", None)
            if (
                drive_consent is None
                or not isinstance(destination, str)
                or any(
                    b.owner != owner or b.model_destination != destination
                    for b in boundaries
                )
            ):
                return _CONSENT_FAILURE
            kind: DriveDataKind = (
                "content"
                if any(b.kind == "content" for b in boundaries)
                or (drive_context is not None and drive_context.kind == "content")
                else "metadata"
            )
            try:
                boundary = drive_consent.authorize_transfer(owner, destination, kind)
                for previous in boundaries:
                    drive_consent.authorize_transfer(owner, destination, previous.kind)
                if drive_context is not None:
                    drive_consent.authorize_transfer(
                        owner, destination, drive_context.kind
                    )
            except DriveConsentRequired:
                return _CONSENT_FAILURE
        try:
            memories = (
                await self._memory_service.recall(owner, user_message)
                if boundary is None
                else ()
            )
        except MemoryUnavailable:
            memories = ()
        except Exception:
            memories = ()
        turn = ModelTurn(
            user_message=user_message,
            system_instruction=build_system_instruction(now),
            current_time=now,
            tools=await self._tools_or_empty(),
            history=history,
            memories=memories,
            drive_context=drive_context,
        )
        try:
            decision = await self._provider.respond(turn)
        except ModelUnavailable:
            return _MODEL_FAILURE
        except Exception:
            return _MODEL_FAILURE

        for _ in range(self._max_tool_rounds):
            if decision.text is not None:
                return await self._complete_turn(
                    session_id,
                    owner,
                    user_message,
                    decision.text,
                    ingest=True,
                    drive_boundary=boundary,
                )
            assert decision.tool_call is not None
            if decision.tool_call.name != _ALLOWED_TOOL:
                return _READ_ONLY
            if self._on_tool_invoked is not None:
                self._on_tool_invoked(_ALLOWED_TOOL)
            try:
                result = await self._calendar_mcp.get_weekly_availability(
                    decision.tool_call.arguments
                )
            except McpUnavailable:
                return _TOOL_FAILURE
            except Exception:
                return _TOOL_FAILURE
            try:
                decision = await self._provider.respond_after_tool(
                    turn,
                    decision.tool_call,
                    ToolResult(_ALLOWED_TOOL, result),
                )
            except ModelUnavailable:
                return _MODEL_FAILURE
            except Exception:
                return _MODEL_FAILURE
            if decision.text is not None:
                return await self._complete_turn(
                    session_id,
                    owner,
                    user_message,
                    decision.text,
                    ingest=False,
                    drive_boundary=boundary,
                )
        return _TOOL_FAILURE

    async def _complete_turn(
        self,
        session_id: str,
        owner: MemoryOwnerId,
        user_message: str,
        assistant_message: str,
        *,
        ingest: bool,
        drive_boundary: DriveBoundary | None = None,
    ) -> str:
        await self._conversation_store.commit_turn(
            session_id, user_message, assistant_message, drive_boundary=drive_boundary
        )
        if ingest and drive_boundary is None:
            try:
                history = await self._conversation_store.load(session_id)
                await self._memory_service.ingest_turn(
                    owner,
                    tuple((message.role, message.content) for message in history),
                    self._memory_conversation_id(session_id),
                )
            except MemoryUnavailable:
                pass
            except Exception:
                pass
        return assistant_message

    def _memory_conversation_id(self, session_id: str) -> str:
        return self._memory_conversation_ids.setdefault(
            session_id, f"{session_id}:{uuid.uuid4().hex}"
        )

    @staticmethod
    def _memory_action(user_message: str) -> tuple[str, str] | None:
        normalized = user_message.strip()
        lowered = normalized.casefold()
        if lowered in {"remember", "remember that"}:
            return "remember", ""
        if lowered in {"forget", "forget that", "forget my preference about"}:
            return "forget", ""
        for prefix, action in (
            ("remember that ", "remember"),
            ("remember ", "remember"),
            ("forget that ", "forget"),
            ("forget my preference about ", "forget"),
            ("forget ", "forget"),
        ):
            if lowered.startswith(prefix):
                return action, normalized[len(prefix) :].strip()
        return None

    async def _perform_memory_action(
        self, owner: MemoryOwnerId, action: str, content: str
    ) -> str:
        try:
            if not content or content.casefold() in {
                "all",
                "everything",
                "all memories",
                "this",
                "that",
                "it",
                "this document",
                "that document",
                "this file",
                "that file",
                "this summary",
                "that summary",
            }:
                raise ValueError("memory request is too broad")
            if action == "remember":
                await self._memory_service.remember(owner, content)
                return "I'll remember that."
            await self._memory_service.forget(owner, content)
            return "I've forgotten that memory."
        except (MemoryUnavailable, ValueError):
            return (
                _MEMORY_SAVE_FAILURE if action == "remember" else _MEMORY_FORGET_FAILURE
            )

    async def _tools_or_empty(self) -> tuple[ToolDefinition, ...]:
        try:
            return tuple(
                tool
                for tool in await self._calendar_mcp.discover_tools()
                if tool.name == _ALLOWED_TOOL
            )
        except McpUnavailable:
            return ()
        except Exception:
            return ()
