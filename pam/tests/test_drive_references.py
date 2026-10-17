"""Stage 8 reference lifecycle, transport and durable-memory boundary tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pam.conversation.file_context import FileReferences, google_file_ids, selection
from pam.conversation.models import ModelDecision
from pam.conversation.store import InMemoryConversationStore, SessionOwnerMismatch
from pam.memory.models import MemoryOwnerId
from pam.telegram.adapter import TelegramAdapter
from pam.tests.test_drive_metadata import harness as metadata_harness  # noqa: F401
from pam.tests.test_drive_routing import (
    CONSENT,
    FILE,
    OWNER,
    PAYLOAD,
    call,
    harness,  # noqa: F401
)
from pam.tests.test_telegram import replies_for

NOW = datetime(2026, 10, 18, tzinfo=UTC)
BOUNDARY = CONSENT.authorize_transfer(OWNER, CONSENT.model_destination, "metadata")
SECOND = FILE | {
    "file_id": "second-id",
    "source_url": "https://drive.google.com/file/d/second-id/view",
}


def refs(payload=None):
    return FileReferences.from_result(
        None,
        BOUNDARY,
        "drive_search_files",
        {"name": "PAM TEST"},
        payload or PAYLOAD,
        NOW,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/file-id/view?usp=sharing",
        "https://drive.google.com/open?id=file-id",
        "https://docs.google.com/document/d/file-id/edit",
        "https://docs.google.com/spreadsheets/d/file-id/edit#gid=0",
        "https://docs.google.com/presentation/d/file-id/view",
    ],
)
def test_recognized_links_are_parsed_locally(url):
    assert google_file_ids(url) == {"file-id"}


@pytest.mark.parametrize(
    "url",
    [
        "http://drive.google.com/file/d/file-id/view",
        "https://drive.google.com.evil.example/file/d/file-id/view",
        "https://evil.example/file-id",
        "https://evil@drive.google.com/file/d/file-id/view",
        "https://drive.google.com:443/file/d/file-id/view",
        "https://drive.google.com/open?id=file-id&id=other",
        "https://drive.google.com/open?id=bad%2Fid",
        "https://drive.google.com:invalid/file/d/file-id/view",
    ],
)
def test_unrecognized_links_are_not_file_authority(url):
    assert google_file_ids(url) == set()


def test_references_have_fixed_expiry_cap_and_private_repr():
    data = PAYLOAD | {"files": [FILE | {"file_id": str(i)} for i in range(70)]}
    saved = refs(data)
    assert len(saved.files) == 50
    assert saved.expires_at == NOW + timedelta(minutes=30)
    assert saved.valid(BOUNDARY, NOW + timedelta(minutes=29))
    assert not saved.valid(BOUNDARY, NOW + timedelta(minutes=30))
    assert "PAM TEST" not in repr(saved)


@pytest.mark.parametrize(
    "text,identifier",
    [
        ("Show metadata for file 2", "second-id"),
        ("the second one", "second-id"),
        ("Show the first document", "file-id"),
        ("2", "second-id"),
    ],
)
def test_numbered_selection_matches_host_display(text, identifier):
    saved = refs(PAYLOAD | {"files": [FILE, SECOND]})
    assert selection(text, saved) == (identifier, None)
    assert '2. "PAM TEST.txt"' in saved.display()


@pytest.mark.parametrize(
    "text", ["Show that file", "Show metadata for PAM TEST.txt", "file 9"]
)
def test_duplicate_names_and_ambiguous_selection_require_clarification(text):
    saved = refs(PAYLOAD | {"files": [FILE, SECOND]})
    assert selection(text, saved)[1] is not None


@pytest.mark.asyncio
async def test_store_expiry_eviction_clear_and_owner_binding():
    store = InMemoryConversationStore(max_sessions=1)
    await store.commit_turn(
        "one",
        "find",
        "answer",
        owner=OWNER,
        drive_boundary=BOUNDARY,
        file_references=refs(),
    )
    assert await store.load_files("one", OWNER, BOUNDARY, NOW)
    with pytest.raises(SessionOwnerMismatch):
        await store.load_files("one", MemoryOwnerId("other"), BOUNDARY, NOW)
    assert (
        await store.load_files("one", OWNER, BOUNDARY, NOW + timedelta(minutes=30))
        is None
    )
    await store.commit_turn(
        "one",
        "find",
        "answer",
        owner=OWNER,
        drive_boundary=BOUNDARY,
        file_references=refs(),
    )
    await store.commit_turn("two", "hello", "hi", owner=OWNER)
    assert await store.load_files("one", OWNER, BOUNDARY, NOW) is None
    assert await store.load("one") == ()
    await store.clear("two")
    assert await store.load("two") == ()


@pytest.mark.asyncio
async def test_cross_turn_numbered_followup_retrieves_fresh_metadata(request):
    h = request.getfixturevalue("harness")
    h.drive.payload = PAYLOAD | {"files": [FILE, SECOND]}
    service, provider = h.build(
        [
            call("drive_search_files", {"name": "PAM TEST"}),
            ModelDecision(text="Found files"),
            call("drive_get_file_metadata", {"file_id": "second-id"}),
            ModelDecision(text="Fresh metadata"),
        ]
    )
    first = await service.respond("Find PAM TEST", memory_owner=OWNER)
    assert '1. "PAM TEST.txt"' in first and '2. "PAM TEST.txt"' in first
    h.drive.payload = PAYLOAD | {"files": [SECOND | {"name": "Renamed.txt"}]}
    answer = await service.respond(
        "Show metadata for the second one", memory_owner=OWNER
    )
    assert "Renamed.txt" in answer
    assert h.drive.calls[-1][1] == {"file_id": "second-id"}
    assert '"selected_file_id": "second-id"' in provider.turns[2].drive_context.text
    assert h.memory.queries == h.memory.ingested == []


@pytest.mark.asyncio
async def test_ambiguous_followup_does_not_call_model_or_google(request):
    h = request.getfixturevalue("harness")
    h.drive.payload = PAYLOAD | {"files": [FILE, SECOND]}
    service, provider = h.build(
        [call("drive_search_files"), ModelDecision(text="Found")]
    )
    await service.respond("Find PAM TEST", memory_owner=OWNER)
    assert "Which file" in await service.respond("Show that file", memory_owner=OWNER)
    assert len(provider.turns) == 2 and len(h.drive.calls) == 1


@pytest.mark.asyncio
async def test_expiry_and_new_prevent_history_from_reviving_references(request):
    h = request.getfixturevalue("harness")
    clock = [NOW]
    service, provider = h.build(
        [call("drive_search_files"), ModelDecision(text="Found")],
        clock=lambda: clock[0],
    )
    await service.respond("Find file", memory_owner=OWNER)
    clock[0] += timedelta(minutes=30)
    assert "expired" in await service.respond("Show that file", memory_owner=OWNER)
    await service.clear("default")
    assert "expired" in await service.respond("Show file 1", memory_owner=OWNER)
    assert len(provider.turns) == 2 and len(h.drive.calls) == 1


@pytest.mark.parametrize("same_query", [True, False])
@pytest.mark.asyncio
async def test_cross_turn_cursor_remains_bound_to_query_and_page_size(
    request, same_query
):
    h = request.getfixturevalue("harness")
    h.drive.payload = PAYLOAD | {"next_page_token": "next-token"}
    service, provider = h.build(
        [
            call("drive_search_files", {"name": "PAM TEST", "page_size": 5}),
            ModelDecision(text="Page one"),
            call(
                "drive_search_files",
                {
                    "name": "PAM TEST",
                    "page_size": 5 if same_query else 6,
                    "page_token": "next-token",
                },
            ),
            ModelDecision(text="Page two"),
        ]
    )
    await service.respond("Find PAM TEST", memory_owner=OWNER)
    await service.respond("Next page", memory_owner=OWNER)
    assert len(h.drive.calls) == (2 if same_query else 1)


@pytest.mark.asyncio
async def test_grant_identity_change_blocks_old_context_before_io(request):
    h = request.getfixturevalue("harness")
    h.consent = replace(CONSENT, grant_identity="original")
    service, provider = h.build(
        [call("drive_search_files"), ModelDecision(text="Found")]
    )
    await service.respond("Find file", memory_owner=OWNER)
    h.consent = replace(h.consent, grant_identity="replacement")
    assert "consent" in await service.respond("Show that file", memory_owner=OWNER)
    assert len(provider.turns) == 2 and len(h.drive.calls) == 1


@pytest.mark.asyncio
async def test_model_cannot_substitute_another_file_for_numbered_selection(request):
    h = request.getfixturevalue("harness")
    h.drive.payload = PAYLOAD | {"files": [FILE, SECOND]}
    service, provider = h.build(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            call("drive_get_file_metadata", {"file_id": "file-id"}),
            ModelDecision(text="Please retry"),
        ]
    )
    await service.respond("Find files", memory_owner=OWNER)
    await service.respond("Show file 2", memory_owner=OWNER)
    assert len(h.drive.calls) == 1
    assert provider.tool_results[-1].result["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.asyncio
async def test_user_link_lookup_never_follows_arbitrary_urls(request, valid):
    h = request.getfixturevalue("harness")
    service, provider = h.build(
        [
            call("drive_get_file_metadata", {"file_id": "file-id"}),
            ModelDecision(text="Result"),
        ]
    )
    host = "drive.google.com" if valid else "evil.example"
    await service.respond(
        f"Get metadata https://{host}/file/d/file-id/view", memory_owner=OWNER
    )
    assert len(h.drive.calls) == int(valid)


@pytest.mark.asyncio
async def test_memory_is_suppressed_through_followups_and_explicit_action_stays_literal(
    request,
):
    h = request.getfixturevalue("harness")
    service, provider = h.build(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            ModelDecision(text="Follow-up"),
            ModelDecision(text="Ordinary answer"),
            ModelDecision(text="Fresh"),
        ]
    )
    await service.respond("Find PAM TEST", memory_owner=OWNER)
    await service.respond("Explain the metadata", memory_owner=OWNER)
    await service.respond("Hello", memory_owner=OWNER)
    assert "couldn't" in await service.respond(
        "Remember the second file", memory_owner=OWNER
    )
    assert "remember" in await service.respond(
        "Remember I prefer short replies", memory_owner=OWNER
    )
    assert h.memory.remembered == [(OWNER, "I prefer short replies")]
    assert h.memory.queries == h.memory.ingested == []
    await service.clear("default")
    h.consent = replace(CONSENT, allow_metadata_transfer=False)
    await service.respond("Hello fresh", memory_owner=OWNER)
    assert h.memory.queries == [(OWNER, "Hello fresh")]
    assert len(h.memory.ingested) == 1


@pytest.mark.asyncio
async def test_no_tool_drive_eligible_turn_also_keeps_memory_boundary(request):
    h = request.getfixturevalue("harness")
    service, provider = h.build([ModelDecision(text="Please clarify")])
    await service.respond("Find my private filename", memory_owner=OWNER)
    h.consent = replace(CONSENT, allow_metadata_transfer=False)
    assert "consent" in await service.respond("Repeat", memory_owner=OWNER)
    assert h.memory.queries == h.memory.ingested == []


@pytest.mark.asyncio
async def test_telegram_uses_shared_followups_and_authorizes_before_any_calls(request):
    h = request.getfixturevalue("harness")
    owner = MemoryOwnerId("telegram:7")
    h.consent = replace(CONSENT, owner=owner)
    service, provider = h.build(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            call("drive_get_file_metadata", {"file_id": "file-id"}),
            ModelDecision(text="Metadata"),
        ]
    )
    adapter = TelegramAdapter(service, (7,), capability_help=service.capability_help)
    assert "Drive metadata" in (await replies_for(adapter, text="/help"))[0]
    await replies_for(adapter, user_id=8)
    await replies_for(adapter, chat_type="group")
    assert provider.turns == [] and h.drive.discoveries == 0
    assert (
        "Verified Drive choices"
        in (await replies_for(adapter, text="Find PAM TEST"))[0]
    )
    assert "Metadata" in (await replies_for(adapter, text="Show that file"))[0]
    assert len(h.drive.calls) == 2
    await replies_for(adapter, text="/new")
    assert "expired" in (await replies_for(adapter, text="Show that file"))[0]
    assert h.memory.queries == h.memory.ingested == []


@pytest.mark.asyncio
async def test_help_is_owner_specific_and_does_not_discover_or_call_model(request):
    h = request.getfixturevalue("harness")
    service, provider = h.build([])
    assert "Drive metadata" in service.capability_help(OWNER)
    assert "Drive metadata" not in service.capability_help(MemoryOwnerId("other"))
    assert h.drive.discoveries == 0 and provider.turns == []


@pytest.mark.asyncio
async def test_cross_session_reference_cannot_authorize_lookup(request):
    h = request.getfixturevalue("harness")
    service, provider = h.build(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            call("drive_get_file_metadata", {"file_id": "file-id"}),
            ModelDecision(text="Denied"),
        ]
    )
    await service.respond("Find file", session_id="one", memory_owner=OWNER)
    await service.respond("Show metadata", session_id="two", memory_owner=OWNER)
    assert len(h.drive.calls) == 1
    assert provider.tool_results[-1].result["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_reference_context_limit_blocks_before_provider_and_memory(request):
    h = request.getfixturevalue("harness")
    await h.store.commit_turn(
        "default",
        "find",
        "answer",
        owner=OWNER,
        drive_boundary=BOUNDARY,
        file_references=refs(),
    )
    service, provider = h.build([], drive_max_context_chars=50, clock=lambda: NOW)
    assert "context limit" in await service.respond("Hello", memory_owner=OWNER)
    assert provider.turns == [] and h.memory.queries == [] and h.drive.discoveries == 0


@pytest.mark.asyncio
async def test_selected_file_plain_answer_cannot_claim_fresh_metadata(request):
    h = request.getfixturevalue("harness")
    service, provider = h.build(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            ModelDecision(text="UNVERIFIED-FRESH-CLAIM"),
        ]
    )
    await service.respond("Find file", memory_owner=OWNER)
    answer = await service.respond("Show that file", memory_owner=OWNER)
    assert "couldn't retrieve current metadata" in answer
    assert "UNVERIFIED" not in answer and len(h.drive.calls) == 1


def test_invalid_cursor_and_unavailable_file_invalidate_saved_reference():
    saved = refs(PAYLOAD | {"files": [FILE, SECOND], "next_page_token": "cursor"})
    updated = FileReferences.from_result(
        saved,
        BOUNDARY,
        "drive_get_file_metadata",
        {"file_id": "file-id"},
        {"error": {"code": "unavailable"}},
        NOW,
    )
    assert [file["file_id"] for file in updated.files] == ["second-id"]
    updated = FileReferences.from_result(
        updated,
        BOUNDARY,
        "drive_search_files",
        {},
        {"error": {"code": "invalid_page_token"}},
        NOW,
    )
    assert updated.next_page_token is None
    assert updated.expires_at == saved.expires_at


def test_incomplete_and_empty_results_display_honestly():
    saved = refs(
        PAYLOAD | {"files": [], "incomplete_search": True, "next_page_token": "cursor"}
    )
    assert "No matching files on this page" in saved.display()
    assert "incomplete search" in saved.display() and "More results" in saved.display()
    assert selection("Next page", saved) == (None, None)
    assert "new search" in selection("Next page", None)[1]


def test_grant_fingerprint_tracks_account_credentials_without_exposing_them(request):
    from pydantic import SecretStr

    state = request.getfixturevalue("metadata_harness")
    original = state.auth.consent(OWNER)
    assert original.grant_identity and original.grant_identity not in repr(original)
    assert state.auth.consent(OWNER).grant_identity == original.grant_identity
    state.auth._save(
        state.auth.load().model_copy(update={"refresh_token": SecretStr("REPLACEMENT")})
    )
    assert state.auth.consent(OWNER).grant_identity != original.grant_identity
    assert state.calls == state.refreshes == []


@pytest.mark.asyncio
async def test_drive_discovery_failure_cannot_reenable_automatic_memory(request):
    h = request.getfixturevalue("harness")

    async def fail():
        raise RuntimeError("PRIVATE")

    h.drive.discover_tools = fail
    service, provider = h.build([ModelDecision(text="Drive unavailable")])
    await service.respond("Find my private filename", memory_owner=OWNER)
    assert h.memory.queries == h.memory.ingested == []
    assert all(message.drive_boundary for message in await h.store.load("default"))


@pytest.mark.asyncio
async def test_cli_reference_followups_use_shared_factory(request, monkeypatch, capsys):
    from pam.config import Settings
    from pam.conversation import cli
    from pam.conversation.provider import ScriptedModelProvider
    from pam.tests.test_drive_routing import DEST

    h = request.getfixturevalue("harness")
    provider = ScriptedModelProvider(
        [
            call("drive_search_files"),
            ModelDecision(text="Found"),
            call("drive_get_file_metadata", {"file_id": "file-id"}),
            ModelDecision(text="Metadata"),
        ],
        data_destination=DEST,
    )
    monkeypatch.setattr(
        "pam.conversation.factory.create_model_provider", lambda _: provider
    )
    monkeypatch.setattr("pam.mcp.server.create_mcp_server", lambda _: object())
    monkeypatch.setattr(
        "pam.conversation.mcp_client.local_client_from_server", lambda _: h.calendar
    )
    monkeypatch.setattr(
        "pam.conversation.mcp_client.local_drive_support",
        lambda *args: (h.drive, lambda _: h.consent),
    )
    monkeypatch.setattr("pam.memory.factory.create_memory_service", lambda _: h.memory)
    messages = iter(
        ["/help", "Find PAM TEST", "Show that file", "/new", "Show that file", "exit"]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    await cli.run(Settings(_env_file=None))
    output = capsys.readouterr().out
    assert "Drive metadata" in output and "Verified Drive choices" in output
    assert "Metadata" in output and "expired" in output
    assert len(h.drive.calls) == 2 and h.memory.queries == h.memory.ingested == []
