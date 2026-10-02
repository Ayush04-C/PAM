"""Offline tests for the BharatCode OpenAI-compatible provider adapter."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from pam.config import Settings
from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.models import ModelTurn, ToolCall, ToolDefinition, ToolResult
from pam.conversation.provider import ModelUnavailable
from pam.domain import DISPLAY_TIMEZONE

TOOL = ToolDefinition(
    "get_weekly_availability",
    "Read Calendar availability.",
    {
        "type": "object",
        "properties": {"timezone": {"type": "string"}},
        "required": ["timezone"],
        "additionalProperties": False,
    },
)
TURN = ModelTurn(
    "How busy am I today?",
    "PAM system instruction with Asia/Kolkata and 2026-10-02.",
    datetime(2026, 10, 2, 9, tzinfo=DISPLAY_TIMEZONE),
    (TOOL,),
)


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def fake_client(responses: list[object]) -> tuple[Any, FakeCompletions]:
    completions = FakeCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def completion(message: object) -> object:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_direct_response_sends_system_user_and_approved_schema() -> None:
    client, completions = fake_client(
        [
            completion(
                SimpleNamespace(content="I can check availability.", tool_calls=[])
            )
        ]
    )
    provider = BharatCodeProvider(
        "bc-key-do-not-leak", "exact-model", "https://x", client=client
    )

    decision = await provider.respond(TURN)

    assert decision.text == "I can check availability."
    request = completions.calls[0]
    assert request["model"] == "exact-model"
    assert request["messages"][0]["content"] == TURN.system_instruction
    assert request["messages"][1]["content"] == TURN.user_message
    assert request["tools"][0]["function"]["parameters"] == dict(TOOL.input_schema)
    assert "bc-key-do-not-leak" not in str(request)


@pytest.mark.asyncio
async def test_tool_call_id_and_result_round_trip() -> None:
    first = completion(
        SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="call-123",
                    function=SimpleNamespace(
                        name="get_weekly_availability",
                        arguments=json.dumps({"timezone": "Asia/Kolkata"}),
                    ),
                )
            ],
        )
    )
    second = completion(SimpleNamespace(content="You are free.", tool_calls=[]))
    client, completions = fake_client([first, second])
    provider = BharatCodeProvider("key", "model", "https://x", client=client)

    decision = await provider.respond(TURN)
    assert decision.tool_call == ToolCall(
        "get_weekly_availability", {"timezone": "Asia/Kolkata"}, "call-123"
    )
    final = await provider.respond_after_tool(
        TURN,
        decision.tool_call,
        ToolResult("get_weekly_availability", {"availability": "Free day"}),
    )

    assert final.text == "You are free."
    messages = completions.calls[1]["messages"]
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-123",
        "content": '{"availability":"Free day"}',
    }


@pytest.mark.asyncio
async def test_malformed_provider_tool_call_and_network_failure_map_safely() -> None:
    malformed_client, _ = fake_client(
        [
            completion(
                SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-123",
                            function=SimpleNamespace(
                                name="get_weekly_availability", arguments="not-json"
                            ),
                        )
                    ],
                )
            )
        ]
    )
    provider = BharatCodeProvider("key", "model", "https://x", client=malformed_client)
    with pytest.raises(ModelUnavailable):
        await provider.respond(TURN)

    class FailingCompletions:
        async def create(self, **kwargs: Any) -> object:
            raise RuntimeError("BHARATCODE_KEY_DO_NOT_LEAK")

    failing_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )
    provider = BharatCodeProvider("key", "model", "https://x", client=failing_client)
    with pytest.raises(ModelUnavailable) as error:
        await provider.respond(TURN)
    assert "BHARATCODE_KEY_DO_NOT_LEAK" not in str(error.value)


def test_provider_specific_settings_are_conditionally_required() -> None:
    bharatcode = Settings(
        _env_file=None,
        model_provider="bharatcode",
        bharatcode_api_key="bharatcode-key",
    )
    assert bharatcode.gemini_api_key is None
    gemini = Settings(
        _env_file=None,
        model_provider="gemini",
        gemini_api_key="gemini-key",
    )
    assert gemini.bharatcode_api_key is None
    with pytest.raises(ValueError, match="BHARATCODE_API_KEY"):
        Settings(_env_file=None, model_provider="bharatcode")
