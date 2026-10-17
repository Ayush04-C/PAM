"""Stage 2 provider serialization and destination binding without network calls."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from google.genai import types

from pam.conversation.bharatcode import BharatCodeProvider
from pam.conversation.gemini import GeminiProvider
from pam.conversation.models import ConversationMessage, DriveBoundary, DriveContext
from pam.memory.models import MemoryOwnerId
from pam.tests.test_bharatcode import TURN, completion, fake_client

OWNER = MemoryOwnerId("telegram:100")
CONTEXT = DriveContext("Private document text.", "content")


@pytest.mark.asyncio
async def test_bharatcode_context_is_non_system_data_and_api_key_is_absent() -> None:
    client, calls = fake_client(
        [completion(SimpleNamespace(content="Summary", tool_calls=[]))]
    )
    provider = BharatCodeProvider(
        "SECRET_KEY_SENTINEL", "model", "https://example.invalid", client=client
    )
    boundary = DriveBoundary(OWNER, "hidden-destination", "content")
    turn = replace(
        TURN,
        drive_context=CONTEXT,
        history=(ConversationMessage("assistant", "Old summary", boundary),),
    )
    await provider.respond(turn)
    request = calls.calls[0]
    assert request["messages"][0]["role"] == "system"
    assert CONTEXT.text not in request["messages"][0]["content"]
    assert CONTEXT.text in request["messages"][1]["content"]
    assert "untrusted context" in request["messages"][1]["content"]
    assert "SECRET_KEY_SENTINEL" not in str(request)
    assert OWNER.value not in str(request)
    assert CONTEXT.text not in repr(CONTEXT)
    assert "hidden-destination" not in str(request)


def test_gemini_keeps_drive_data_out_of_system_instructions() -> None:
    from pam.tests.test_bharatcode import TURN

    turn = replace(TURN, drive_context=CONTEXT)
    contents = GeminiProvider._initial_contents(turn)
    assert isinstance(contents[0], types.Content)
    assert contents[0].role == "user"
    assert CONTEXT.text in contents[0].parts[0].text
    assert CONTEXT.text not in turn.system_instruction


def test_gemini_consent_destination_matches_pinned_sdk_endpoint(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "pam.conversation.gemini.genai.Client", lambda **kwargs: calls.append(kwargs)
    )
    provider = GeminiProvider("KEY_NOT_FOR_CONTEXT", "model-a")
    assert calls[0]["vertexai"] is False
    assert calls[0]["http_options"].base_url in provider.data_destination
    assert "model-a" in provider.data_destination
    assert "KEY_NOT_FOR_CONTEXT" not in provider.data_destination
