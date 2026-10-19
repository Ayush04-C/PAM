"""Offline tests for the BharatCode OpenAI-compatible provider adapter."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from pam.config import Settings
from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.models import (
    ConversationMessage,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
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
    assert request["tool_choice"] == "auto"
    assert "bc-key-do-not-leak" not in str(request)


@pytest.mark.asyncio
async def test_provider_translates_portable_history_in_chronological_order() -> None:
    client, completions = fake_client(
        [completion(SimpleNamespace(content="Follow-up answer.", tool_calls=[]))]
    )
    provider = BharatCodeProvider("key", "model", "https://x", client=client)
    turn = ModelTurn(
        TURN.user_message,
        TURN.system_instruction,
        TURN.current_time,
        TURN.tools,
        (
            ConversationMessage("user", "What days are free?"),
            ConversationMessage("assistant", "October 3 and 4."),
        ),
    )

    await provider.respond(turn)

    assert completions.calls[0]["messages"] == [
        {"role": "system", "content": TURN.system_instruction},
        {"role": "user", "content": "What days are free?"},
        {"role": "assistant", "content": "October 3 and 4."},
        {"role": "user", "content": TURN.user_message},
    ]


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
@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("after_tool", [False, True])
async def test_sdk_request_accepts_chat_and_tool_continuations(
    with_tools: bool, after_tool: bool
) -> None:
    """Exercise real SDK serialization against an endpoint rejecting empty tools."""
    import httpx
    from openai import AsyncOpenAI

    requests: list[dict[str, Any]] = []

    def endpoint(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("tools") == [] or (
            "tool_choice" in payload and "tools" not in payload
        ):
            return httpx.Response(400, json={"error": {"message": "invalid tools"}})
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Hello."},
                    }
                ],
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http,
        AsyncOpenAI(
            api_key="synthetic-key",
            base_url="https://example.test/v1",
            http_client=http,
            max_retries=0,
        ) as sdk,
    ):
        provider = BharatCodeProvider("key", "model", "https://x", client=sdk)
        turn = replace(TURN, tools=TURN.tools if with_tools else ())
        if after_tool:
            result = await provider.respond_after_tool(
                turn,
                ToolCall(TOOL.name, {}, "call-1"),
                ToolResult(TOOL.name, {"availability": "Free day"}),
            )
        else:
            result = await provider.respond(turn)
    assert result.text == "Hello."
    request = requests[0]
    assert ("tools" in request) is with_tools
    assert ("tool_choice" in request) is with_tools
    if after_tool:
        assert request["messages"][-1]["role"] == "tool"
        assert request["messages"][-1]["tool_call_id"] == "call-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "category", "status"),
    [
        ("bad_request", "bad_request", 400),
        ("timeout", "timeout", None),
        ("invalid", "invalid_response", None),
        ("unexpected", "unexpected_error", None),
    ],
)
@pytest.mark.parametrize("after_tool", [False, True])
async def test_failure_logs_are_safe_and_identify_request_phase(
    failure: str,
    category: str,
    status: int | None,
    after_tool: bool,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from openai import APITimeoutError, BadRequestError

    from pam.logging import JsonFormatter

    private = "PRIVATE-KEY-PROMPT-DOCUMENT"
    monkeypatch.setattr(logging.getLogger("pam"), "propagate", True)

    class FailingCompletions:
        async def create(self, **kwargs: Any) -> object:
            request = httpx.Request("POST", "https://example.test/" + private)
            if failure == "bad_request":
                raise BadRequestError(
                    private,
                    response=httpx.Response(400, request=request),
                    body={"message": private},
                )
            if failure == "timeout":
                raise APITimeoutError(request=request)
            if failure == "unexpected":
                raise RuntimeError(private)
            return completion(SimpleNamespace(content=None, tool_calls=[]))

    client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    provider = BharatCodeProvider(private, "model", "https://x", client=client)
    turn = replace(TURN, user_message=private)
    with pytest.raises(ModelUnavailable):
        if after_tool:
            await provider.respond_after_tool(
                turn,
                ToolCall(TOOL.name, {}, "call-1"),
                ToolResult(TOOL.name, {"availability": private}),
            )
        else:
            await provider.respond(turn)
    records = [r for r in caplog.records if r.name == "pam.conversation.bharatcode"]
    assert len(records) == 1
    payload = json.loads(JsonFormatter().format(records[0]))
    assert payload["failure_kind"] == category
    assert payload["http_status"] == status
    assert payload["phase"] == ("after_tool" if after_tool else "initial")
    assert payload["tool_count"] == 1
    assert payload["elapsed_ms"] >= 0
    assert records[0].exc_info is None
    assert private not in json.dumps(payload)


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


@pytest.mark.asyncio
async def test_timeout_is_classified_without_exposing_request_or_credentials():
    import httpx
    from openai import APITimeoutError

    from pam.conversation.provider import ModelTimeout

    class TimeoutCompletions:
        async def create(self, **kwargs):
            raise APITimeoutError(request=httpx.Request("POST", "https://x/PRIVATE"))

    client = SimpleNamespace(chat=SimpleNamespace(completions=TimeoutCompletions()))
    provider = BharatCodeProvider("PRIVATE-KEY", "model", "https://x", client=client)
    with pytest.raises(ModelTimeout) as error:
        await provider.respond(TURN)
    assert "PRIVATE" not in str(error.value) and error.value.__cause__ is None


def test_timeout_configuration_is_bounded_and_used_by_client(monkeypatch):
    from pam.conversation import bharatcode
    from pam.conversation.factory import create_model_provider

    captured = {}

    def client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(bharatcode, "AsyncOpenAI", client)
    settings = Settings(
        _env_file=None,
        model_provider="bharatcode",
        bharatcode_api_key="key",
        bharatcode_timeout_seconds=90,
    )
    provider = create_model_provider(settings)
    assert captured["timeout"] == 90
    assert provider.data_destination.endswith("|" + settings.bharatcode_model)
    for value in (0, 181):
        with pytest.raises(ValueError):
            Settings(_env_file=None, bharatcode_timeout_seconds=value)
