"""Bounded orchestration of an untrusted model and approved MCP tool."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pam.conversation.mcp_client import CalendarMcpClient, McpUnavailable
from pam.conversation.models import ModelTurn, ToolDefinition, ToolResult
from pam.conversation.provider import ModelProvider, ModelUnavailable
from pam.conversation.system_prompt import build_system_instruction
from pam.domain import DISPLAY_TIMEZONE

_ALLOWED_TOOL = "get_weekly_availability"
_TOOL_FAILURE = "I couldn't retrieve calendar availability. Please try again."
_MODEL_FAILURE = "PAM's conversation service is unavailable. Please try again."
_READ_ONLY = "Calendar access is currently read-only; I can't change events."


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
    ) -> None:
        self._provider = provider
        self._calendar_mcp = calendar_mcp
        self._clock = clock or (lambda: datetime.now(DISPLAY_TIMEZONE))
        self._max_tool_rounds = max_tool_rounds
        self._on_tool_invoked = on_tool_invoked

    async def respond(self, user_message: str) -> str:
        """Return a safe text answer without exposing provider or MCP internals."""
        if not user_message.strip():
            return "Please ask a Calendar availability question."
        now = self._clock()
        turn = ModelTurn(
            user_message=user_message,
            system_instruction=build_system_instruction(now),
            current_time=now,
            tools=await self._tools_or_empty(),
        )
        try:
            decision = await self._provider.respond(turn)
        except ModelUnavailable:
            return _MODEL_FAILURE
        except Exception:
            return _MODEL_FAILURE

        for _ in range(self._max_tool_rounds):
            if decision.text is not None:
                return decision.text
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
        return _TOOL_FAILURE

    async def _tools_or_empty(self) -> tuple[ToolDefinition, ...]:
        try:
            return await self._calendar_mcp.discover_tools()
        except McpUnavailable:
            return ()
        except Exception:
            return ()
