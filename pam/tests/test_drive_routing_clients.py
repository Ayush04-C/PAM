"""Stage 7 strict client, provider serialization and real-MCP integration tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from mcp.server import MCPServer

from pam.conversation import mcp_client
from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.gemini import GeminiProvider
from pam.conversation.mcp_client import LocalDriveMcpClient, McpUnavailable
from pam.conversation.models import (
    ModelDecision,
    ModelTurn,
    ToolCall,
    ToolExchange,
    ToolResult,
)
from pam.conversation.provider import ModelUnavailable, ScriptedModelProvider
from pam.conversation.service import ConversationService
from pam.mcp.driver import create_drive_tools
from pam.tests.test_drive_metadata import harness as metadata_harness  # noqa: F401
from pam.tests.test_drive_routing import DEST, OWNER, PAYLOAD, Calendar


@pytest.fixture
def client_state(monkeypatch):
    state = SimpleNamespace(payload=PAYLOAD, is_error=False, calls=[])

    class Client:
        def __init__(self, server):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def call_tool(self, name, arguments):
            state.calls.append((name, arguments))
            return SimpleNamespace(
                structured_content=state.payload, is_error=state.is_error
            )

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name=name)
                    for name in (
                        "drive_search_files",
                        "drive_get_file_metadata",
                        "delete_file",
                    )
                ]
            )

    monkeypatch.setattr(mcp_client, "Client", Client)
    state.client = LocalDriveMcpClient(object(), OWNER)
    return state


@pytest.mark.asyncio
async def test_client_uses_host_schemas_and_ignores_unapproved_discovery(client_state):
    tools = await client_state.client.discover_tools()
    assert {t.name for t in tools} == {"drive_search_files", "drive_get_file_metadata"}
    assert all("owner" not in t.input_schema["properties"] for t in tools)


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("delete_file", {}),
        ("drive_search_files", {"owner": "PRIVATE"}),
        ("drive_search_files", {"page_size": "10"}),
        ("drive_search_files", {"page_size": True}),
        ("drive_get_file_metadata", {"file_id": "../bad"}),
    ],
)
@pytest.mark.asyncio
async def test_client_rejects_invalid_calls_before_mcp(client_state, name, arguments):
    with pytest.raises(McpUnavailable):
        await client_state.client.call_tool(name, arguments, OWNER)
    assert client_state.calls == []


@pytest.mark.asyncio
async def test_client_owner_binding_cannot_be_bypassed(client_state):
    from pam.memory.models import MemoryOwnerId

    with pytest.raises(McpUnavailable):
        await client_state.client.call_tool(
            "drive_search_files", {}, MemoryOwnerId("other")
        )
    assert client_state.calls == []


@pytest.mark.parametrize(
    "change",
    ["source", "content", "trusted", "extra", "link", "id", "cursor", "error-flag"],
)
@pytest.mark.asyncio
async def test_client_rejects_malformed_or_untrusted_result_contract(
    client_state, change
):
    payload = dict(PAYLOAD)
    if change == "source":
        payload["source"] = "unknown"
    if change == "content":
        payload["data_kind"] = "content"
    if change == "trusted":
        payload["untrusted"] = False
    if change == "extra":
        payload["credential"] = "PRIVATE-TOKEN"
    if change == "link":
        payload["files"] = [PAYLOAD["files"][0] | {"source_url": "https://evil.test"}]
    if change == "id":
        payload["files"] = [PAYLOAD["files"][0] | {"file_id": "../bad"}]
    if change == "cursor":
        payload["next_page_token"] = "bad token"
    if change == "error-flag":
        client_state.is_error = True
    client_state.payload = payload
    with pytest.raises(McpUnavailable) as error:
        await client_state.client.call_tool("drive_search_files", {}, OWNER)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
async def test_client_accepts_validated_metadata_and_sanitizes_error_message(
    client_state,
):
    result = await client_state.client.call_tool(
        "drive_search_files", {"name": "null"}, OWNER
    )
    assert result["files"][0]["file_id"] == "file-id"
    assert client_state.calls[0][1]["name"] == "null"
    client_state.payload = PAYLOAD | {
        "files": [],
        "error": {
            "code": "rate_limited",
            "message": "PRIVATE-TOKEN",
            "retryable": False,
        },
    }
    client_state.is_error = True
    result = await client_state.client.call_tool("drive_search_files", {}, OWNER)
    assert "PRIVATE" not in str(result)
    assert result["error"]["retryable"] is True


def turn_with_exchanges():
    exchanges = (
        ToolExchange(
            ToolCall("drive_search_files", {"name": "PAM TEST"}, "one"),
            ToolResult("drive_search_files", PAYLOAD),
        ),
        ToolExchange(
            ToolCall("drive_get_file_metadata", {"file_id": "file-id"}, "two"),
            ToolResult("drive_get_file_metadata", PAYLOAD),
        ),
    )
    return ModelTurn(
        "Find file and check Calendar",
        "system rules",
        datetime.now(),
        (),
        tool_exchanges=exchanges,
    )


@pytest.mark.asyncio
async def test_bharatcode_serializes_every_prior_call_and_result_in_order():
    provider = object.__new__(BharatCodeProvider)
    requests = []

    async def completion(messages, turn):
        requests.append(messages)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(tool_calls=[], content="Answer")
                )
            ]
        )

    provider._create_completion = completion
    call = ToolCall("get_weekly_availability", {}, "three")
    await provider.respond_after_tool(
        turn_with_exchanges(), call, ToolResult(call.name, {"availability": "Free"})
    )
    messages = requests[0]
    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == [
        "one",
        "two",
        "three",
    ]
    assert "google_drive" in messages[3]["content"]


@pytest.mark.asyncio
async def test_gemini_serializes_every_prior_call_and_result_in_order():
    provider = object.__new__(GeminiProvider)
    requests = []

    async def generate(contents, turn):
        requests.append(contents)
        return SimpleNamespace(function_calls=[], text="Answer")

    provider._generate = generate
    call = ToolCall("get_weekly_availability", {})
    await provider.respond_after_tool(
        turn_with_exchanges(), call, ToolResult(call.name, {"availability": "Free"})
    )
    contents = requests[0]
    assert len(contents) == 7
    assert [contents[index].parts[0].function_call.name for index in (1, 3, 5)] == [
        "drive_search_files",
        "drive_get_file_metadata",
        "get_weekly_availability",
    ]
    assert contents[2].parts[0].function_response.response["untrusted"] is True


def test_providers_reject_parallel_tool_calls():
    with pytest.raises(ModelUnavailable):
        BharatCodeProvider._decision_from_message(
            SimpleNamespace(tool_calls=[object(), object()])
        )
    with pytest.raises(ModelUnavailable):
        GeminiProvider._decision_from_response(
            SimpleNamespace(function_calls=[object(), object()])
        )


@pytest.mark.asyncio
async def test_real_metadata_reader_mcp_client_and_conversation_work_together(request):
    state = request.getfixturevalue("metadata_harness")
    state.auth.model_destination = DEST
    state.auth.set_permissions(
        allow_read=True, allow_metadata_transfer=True, confirmed_destination=DEST
    )
    server = MCPServer("Routing test", tools=create_drive_tools(state.reader))
    provider = ScriptedModelProvider(
        [
            ModelDecision(
                tool_call=ToolCall("drive_search_files", {"name": "PAM TEST"})
            ),
            ModelDecision(
                tool_call=ToolCall(
                    "drive_get_file_metadata", {"file_id": "test-file_1"}
                )
            ),
            ModelDecision(text="Found metadata"),
        ],
        data_destination=DEST,
    )
    service = ConversationService(
        provider,
        Calendar(),
        drive_mcp=LocalDriveMcpClient(server, OWNER),
        drive_consent_loader=state.auth.consent,
    )
    assert (
        await service.respond("Find PAM TEST", memory_owner=OWNER) == "Found metadata"
    )
    assert len(state.calls) == len(state.refreshes) == 2
    assert provider.tool_results[-1].result["untrusted"] is True
