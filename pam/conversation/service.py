"""Bounded, consent-gated orchestration of Calendar and Drive read tools."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from typing import Any

from pam.conversation.file_context import FileReferences, google_file_ids, selection
from pam.conversation.mcp_client import (
    DRIVE_CONTENT_TOOL,
    DRIVE_TOOLS,
    CalendarMcpClient,
    DriveMcpClient,
    McpUnavailable,
)
from pam.conversation.models import (
    DriveBoundary,
    DriveConsent,
    DriveContext,
    DriveDataKind,
    ModelTurn,
    ToolDefinition,
    ToolExchange,
    ToolResult,
)
from pam.conversation.provider import ModelProvider
from pam.conversation.store import (
    ConversationStore,
    InMemoryConversationStore,
    SessionOwnerMismatch,
)
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
    """Route allowlisted reads while keeping Drive provenance and consent intact."""

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
        drive_mcp: DriveMcpClient | None = None,
        drive_consent_loader: Callable[[MemoryOwnerId], DriveConsent] | None = None,
        drive_content_enabled: bool = False,
    ) -> None:
        if not 1 <= drive_max_context_chars <= 20_000:
            raise ValueError("Drive context limit must be between 1 and 20000")
        self._drive_max_context_chars = drive_max_context_chars
        self._drive_mcp = drive_mcp
        self._drive_consent_loader = drive_consent_loader
        self._drive_content_enabled = drive_content_enabled
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

    def capability_help(self, owner: MemoryOwnerId) -> str:
        """Describe only locally authorized capabilities; never make API calls."""
        text = (
            "Ask about Calendar availability, for example: Am I free tomorrow? "
            "Calendar access is read-only. Use /new to clear conversation history "
            "and temporary file choices; saved memories are preserved."
        )
        if self._drive_mcp is not None and self._authorize(owner, None, "metadata"):
            text += (
                " Drive metadata search is enabled for your owner: try Find PAM TEST, "
                "then Show metadata for file 2, or Ask for the next page. "
                "Content reading requires separate permission. "
                "Calendar and Drive can be used together."
            )
            if self._drive_content_enabled and self._authorize(owner, None, "content"):
                text += (
                    " Google Docs and UTF-8 text summaries with passages are enabled."
                )
        return text

    async def _respond_in_session(
        self,
        user_message: str,
        session_id: str,
        owner: MemoryOwnerId,
        drive_context: DriveContext | None,
        drive_consent: DriveConsent | None,
    ) -> str:
        """Route bounded sequential calls; gate every sensitive model request."""
        now = self._clock()
        drive_permission = (
            self._authorize(owner, drive_consent, "metadata")
            if self._drive_mcp is not None
            else None
        )
        try:
            references = await self._conversation_store.load_files(
                session_id, owner, drive_permission, now
            )
        except SessionOwnerMismatch:
            return _CONSENT_FAILURE
        history = await self._conversation_store.load(session_id)
        required = [m.drive_boundary for m in history if m.drive_boundary is not None]
        if drive_context is not None:
            permission = self._authorize(owner, drive_consent, drive_context.kind)
            if permission is None:
                return _CONSENT_FAILURE
            required.append(permission)
        if not self._permissions_match(owner, drive_consent, required):
            return _CONSENT_FAILURE
        selected, clarification = selection(user_message, references)
        if clarification and self._drive_mcp is not None:
            return clarification if drive_permission else _CONSENT_FAILURE
        if references is not None:
            text = references.context(selected)
            if drive_context is not None:
                text += "\n" + drive_context.text
            if len(text) > self._drive_max_context_chars:
                return (
                    "Drive references exceed the configured context limit. "
                    "Use /new and search for fewer files."
                )
            drive_context = DriveContext(
                text, drive_context.kind if drive_context else "metadata"
            )
            required.append(references.boundary)
        if drive_permission is not None:
            # Even a no-tool answer can retain a private filename from the user.
            # Keep this session conservative until /new, including discovery failure.
            required.append(drive_permission)
        tools = list(await self._tools_or_empty())
        if drive_permission is not None and self._drive_mcp is not None:
            with suppress(Exception):
                tools.extend(
                    tool
                    for tool in await self._drive_mcp.discover_tools()
                    if tool.name in DRIVE_TOOLS
                    and (
                        tool.name != DRIVE_CONTENT_TOOL
                        or (
                            self._drive_content_enabled
                            and self._authorize(owner, drive_consent, "content")
                            is not None
                        )
                    )
                )
        drive_offered = any(tool.name in DRIVE_TOOLS for tool in tools)
        # A tool-eligible request can include private filenames before retrieval.
        # Conservatively avoid all automatic memory I/O on these turns.
        try:
            memories = (
                await self._memory_service.recall(owner, user_message)
                if not required and not drive_offered
                else ()
            )
        except Exception:
            memories = ()
        turn = ModelTurn(
            user_message=user_message,
            system_instruction=build_system_instruction(now),
            current_time=now,
            tools=tuple(tools),
            history=history,
            memories=memories,
            drive_context=drive_context,
        )
        if not self._permissions_match(owner, drive_consent, required):
            return _CONSENT_FAILURE
        if drive_offered and self._authorize(owner, drive_consent, "metadata") is None:
            turn = replace(
                turn, tools=tuple(t for t in turn.tools if t.name not in DRIVE_TOOLS)
            )
            drive_offered = False
        try:
            decision = await self._provider.respond(turn)
        except Exception:
            return _MODEL_FAILURE
        limit = 6 if drive_offered else self._max_tool_rounds
        calendar_calls = 0
        calls = 0
        drive_chars = len(drive_context.text) if drive_context is not None else 0
        reference_updated = False
        while True:
            if not self._permissions_match(owner, drive_consent, required):
                return self._partial_answer(turn, _CONSENT_FAILURE)
            if decision.text is not None:
                content_attempts = [
                    e for e in turn.tool_exchanges if e.call.name == DRIVE_CONTENT_TOOL
                ]
                if content_attempts and all(
                    e.result.result.get("error") is not None for e in content_attempts
                ):
                    return self._partial_answer(
                        turn,
                        "File content could not be read. "
                        "Check its format, size, permissions or connection.",
                    )
                if selected is not None and not any(
                    exchange.call.name
                    in {"drive_get_file_metadata", DRIVE_CONTENT_TOOL}
                    and exchange.call.arguments.get("file_id") == selected
                    and exchange.result.result.get("error") is None
                    for exchange in turn.tool_exchanges
                ):
                    return self._partial_answer(
                        turn,
                        "I couldn't retrieve current metadata for the selected file. "
                        "Please retry.",
                    )
                boundary = next((b for b in required if b.kind == "content"), None)
                boundary = boundary or next(iter(required), None)
                answer = decision.text
                citation_sources = self._content_sources(turn, answer)
                if citation_sources is None:
                    return self._partial_answer(
                        turn,
                        "I couldn't verify the summary's source passages. "
                        "Please retry.",
                    )
                if citation_sources:
                    answer += "\n\nVerified content sources:\n" + "\n".join(
                        citation_sources
                    )
                if reference_updated and references is not None:
                    answer += "\n\n" + references.display()
                return await self._complete_turn(
                    session_id,
                    owner,
                    user_message,
                    answer,
                    ingest=calls == 0 and not drive_offered,
                    drive_boundary=boundary,
                    file_references=references,
                )
            if calls >= limit:
                if not drive_offered:
                    return _TOOL_FAILURE
                return self._partial_answer(
                    turn, "The tool-call limit was reached. Please narrow the request."
                )
            assert decision.tool_call is not None
            call = decision.tool_call
            if call.call_id is not None and any(
                exchange.call.call_id == call.call_id
                for exchange in turn.tool_exchanges
            ):
                return self._partial_answer(
                    turn, "The model repeated a tool-call identifier. Please retry."
                )
            if (call.name != _ALLOWED_TOOL and call.name not in DRIVE_TOOLS) or (
                call.name == DRIVE_CONTENT_TOOL and not self._drive_content_enabled
            ):
                return self._partial_answer(
                    turn,
                    "Calendar and Drive are read-only; only availability and "
                    "approved file reads are supported."
                    if self._drive_content_enabled and drive_offered
                    else "Calendar and Drive are read-only; only availability and "
                    "file metadata are supported."
                    if drive_offered
                    else _READ_ONLY,
                )
            is_drive = call.name in DRIVE_TOOLS
            if is_drive:
                is_content = call.name == DRIVE_CONTENT_TOOL
                permission = self._authorize(
                    owner, drive_consent, "content" if is_content else "metadata"
                )
                offered_names = {tool.name for tool in turn.tools}
                if (
                    permission is None
                    or call.name not in offered_names
                    or not drive_offered
                    or self._drive_mcp is None
                ):
                    return self._partial_answer(turn, _CONSENT_FAILURE)
                required.append(permission)
                if not self._reference_allowed(
                    turn, call.name, dict(call.arguments), references, selected
                ):
                    result = self._drive_error("invalid_request", content=is_content)
                else:
                    if self._on_tool_invoked is not None:
                        self._on_tool_invoked(call.name)
                    try:
                        result = dict(
                            await self._drive_mcp.call_tool(
                                call.name, call.arguments, owner
                            )
                        )
                    except Exception:
                        result = self._drive_error(
                            "temporary_failure", content=is_content
                        )
                drive_chars += len(
                    json.dumps(
                        {"arguments": dict(call.arguments), "result": result},
                        ensure_ascii=False,
                    )
                )
                if drive_chars > self._drive_max_context_chars:
                    return self._partial_answer(
                        turn,
                        "Drive data exceeds the configured context limit. "
                        "Request fewer files.",
                    )
                previous_references = references
                references = FileReferences.from_result(
                    references,
                    replace(permission, kind="metadata"),
                    call.name,
                    dict(call.arguments),
                    result,
                    now,
                )
                reference_updated = (
                    reference_updated
                    or result.get("error") is None
                    or references != previous_references
                )
            else:
                if calendar_calls >= self._max_tool_rounds:
                    return self._partial_answer(
                        turn,
                        "The Calendar tool-call limit was reached. "
                        "Please narrow the request.",
                    )
                calendar_calls += 1
                if self._on_tool_invoked is not None:
                    self._on_tool_invoked(_ALLOWED_TOOL)
                try:
                    result = dict(
                        await self._calendar_mcp.get_weekly_availability(call.arguments)
                    )
                except Exception:
                    if not drive_offered:
                        return _TOOL_FAILURE
                    result = {
                        "error": {
                            "code": "calendar_unavailable",
                            "message": _TOOL_FAILURE,
                        }
                    }
            calls += 1
            if not self._permissions_match(owner, drive_consent, required):
                return self._partial_answer(turn, _CONSENT_FAILURE)
            if (
                drive_offered
                and self._authorize(owner, drive_consent, "metadata") is None
            ):
                turn = replace(
                    turn,
                    tools=tuple(t for t in turn.tools if t.name not in DRIVE_TOOLS),
                )
            completed_turn = replace(
                turn,
                tool_exchanges=(
                    *turn.tool_exchanges,
                    ToolExchange(call, ToolResult(call.name, result)),
                ),
            )
            try:
                decision = await self._provider.respond_after_tool(
                    turn, call, ToolResult(call.name, result)
                )
            except Exception:
                return self._partial_answer(completed_turn, _MODEL_FAILURE)
            turn = completed_turn

    def _authorize(
        self,
        owner: MemoryOwnerId,
        supplied: DriveConsent | None,
        kind: DriveDataKind,
    ) -> DriveBoundary | None:
        try:
            consent = (
                self._drive_consent_loader(owner)
                if self._drive_consent_loader
                else supplied
            )
            destination = getattr(self._provider, "data_destination", None)
            if consent is None or not isinstance(destination, str):
                return None
            return consent.authorize_transfer(owner, destination, kind)
        except Exception:
            return None

    def _permissions_match(
        self,
        owner: MemoryOwnerId,
        supplied: DriveConsent | None,
        required: list[DriveBoundary],
    ) -> bool:
        destination = getattr(self._provider, "data_destination", None)
        if any(
            b.owner != owner or b.model_destination != destination for b in required
        ):
            return False
        return all(
            self._authorize(owner, supplied, boundary.kind) == boundary
            for boundary in required
        )

    @staticmethod
    def _reference_allowed(
        turn: ModelTurn,
        name: str,
        arguments: dict[str, Any],
        references: FileReferences | None = None,
        selected: str | None = None,
    ) -> bool:
        if name in {"drive_get_file_metadata", DRIVE_CONTENT_TOOL}:
            identifier = arguments.get("file_id")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,256}", identifier
            ):
                return False
            known = {
                file["file_id"]
                for exchange in turn.tool_exchanges
                if exchange.call.name in DRIVE_TOOLS
                for file in exchange.result.result.get("files", [])
            }
            if references:
                known.update(file["file_id"] for file in references.files)
            if selected is not None and identifier != selected:
                return False
            # URL text must match the recognized Google URL parser, not merely
            # contain an ID inside an attacker-controlled URL.
            direct_text = re.sub(r"https?://\S+", "", turn.user_message)
            explicit = re.search(
                r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])",
                direct_text,
            )
            return (
                identifier in known
                or explicit is not None
                or identifier in google_file_ids(turn.user_message)
            )
        token = arguments.get("page_token")
        if token is None:
            return True
        if (
            references
            and references.next_page_token == token
            and (
                references.query == arguments.get("name")
                and references.page_size == arguments.get("page_size", 10)
            )
        ):
            return True
        return any(
            exchange.call.name == "drive_search_files"
            and exchange.result.result.get("next_page_token") == token
            and exchange.call.arguments.get("name") == arguments.get("name")
            and exchange.call.arguments.get("page_size", 10)
            == arguments.get("page_size", 10)
            for exchange in turn.tool_exchanges
        )

    @staticmethod
    def _drive_error(code: str, *, content: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": "google_drive",
            "data_kind": "metadata",
            "untrusted": True,
            "files": [],
            "next_page_token": None,
            "incomplete_search": False,
            "error": {
                "code": code,
                "message": "Drive read request failed safely. "
                "Check the request or reconnect.",
                "retryable": code == "temporary_failure",
            },
        }
        if content:
            result.update(data_kind="content", passages=[], complete=True)
            result.pop("next_page_token")
            result.pop("incomplete_search")
        return result

    @staticmethod
    def _content_sources(turn: ModelTurn, answer: str) -> list[str] | None:
        """Validate citation identities, not the semantic truth of a summary."""
        sources: dict[str, str] = {}
        citations: set[str] = set()
        for exchange in turn.tool_exchanges:
            if (
                exchange.call.name != DRIVE_CONTENT_TOOL
                or exchange.result.result.get("error") is not None
            ):
                continue
            result = exchange.result.result
            for file in result.get("files", []):
                sources[file["file_id"]] = file["source_url"]
                citations.update(
                    f"[{file['file_id']}:{p['label']}]"
                    for p in result.get("passages", [])
                )
        if not sources:
            return []
        used = re.findall(r"\[[^\]\n]{1,256}:P[^\]\n]{1,20}\]|\[P\d+\]", answer)
        links = re.findall(r"https?://[^\s<>]+", answer)
        if (
            not used
            or any(c not in citations for c in used)
            or any(link.rstrip(").,") not in sources.values() for link in links)
        ):
            return None
        return [f"{identifier}: {url}" for identifier, url in sources.items()]

    @staticmethod
    def _partial_answer(turn: ModelTurn, reason: str) -> str:
        for exchange in reversed(turn.tool_exchanges):
            if exchange.call.name == _ALLOWED_TOOL:
                availability = exchange.result.result.get("availability")
                if isinstance(availability, str):
                    return availability + "\n\n" + reason
        return reason

    async def _complete_turn(
        self,
        session_id: str,
        owner: MemoryOwnerId,
        user_message: str,
        assistant_message: str,
        *,
        ingest: bool,
        drive_boundary: DriveBoundary | None = None,
        file_references: FileReferences | None = None,
    ) -> str:
        await self._conversation_store.commit_turn(
            session_id,
            user_message,
            assistant_message,
            drive_boundary=drive_boundary,
            file_references=file_references,
            owner=owner,
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
            if (
                selection(content, None)[1] is not None
                or not content
                or content.casefold()
                in {
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
                }
            ):
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
