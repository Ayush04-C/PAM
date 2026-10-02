"""Provider-neutral interface and deterministic offline provider."""

from __future__ import annotations

from collections import deque
from typing import Protocol

from pam.conversation.models import ModelDecision, ModelTurn, ToolCall, ToolResult


class ModelUnavailable(RuntimeError):
    """A model provider could not safely produce a usable response."""


class ModelProvider(Protocol):
    """Minimal model surface required by the conversation orchestrator."""

    async def respond(self, turn: ModelTurn) -> ModelDecision:
        """Return the initial decision for a user request."""

    async def respond_after_tool(
        self, turn: ModelTurn, tool_call: ToolCall, tool_result: ToolResult
    ) -> ModelDecision:
        """Return the next decision after receiving structured tool data."""


class ScriptedModelProvider:
    """Offline deterministic provider used to test orchestration behavior."""

    def __init__(self, decisions: list[ModelDecision]) -> None:
        self._decisions = deque(decisions)
        self.turns: list[ModelTurn] = []
        self.tool_results: list[ToolResult] = []

    async def respond(self, turn: ModelTurn) -> ModelDecision:
        self.turns.append(turn)
        return self._next_decision()

    async def respond_after_tool(
        self, turn: ModelTurn, tool_call: ToolCall, tool_result: ToolResult
    ) -> ModelDecision:
        self.turns.append(turn)
        self.tool_results.append(tool_result)
        return self._next_decision()

    def _next_decision(self) -> ModelDecision:
        if not self._decisions:
            raise ModelUnavailable("model provider is unavailable")
        return self._decisions.popleft()
