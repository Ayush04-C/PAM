"""Shared MCP discovery, strict metadata tools and direct CLI diagnostics."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server import MCPServer

from pam.application import AvailabilityService
from pam.conversation.mcp_client import local_client_from_server
from pam.integrations.google_drive import DriveFile, DrivePage, DriveReadError
from pam.mcp import server as composition
from pam.mcp.calendar import create_calendar_tool
from pam.mcp.driver import create_drive_tools
from pam.memory.models import MemoryOwnerId
from pam.tests.test_drive_metadata import harness as metadata_harness  # noqa: F401
from pam.tests.test_drive_oauth import enabled_settings
from pam.tests.test_mcp_calendar import REQUEST, FailingReader, fake_service

OWNER = MemoryOwnerId("cli-local")
FILE = DriveFile(
    "test-file",
    "PAM TEST.txt",
    "text/plain",
    None,
    "https://drive.google.com/file/d/test-file/view",
)


class Reader:
    owner = OWNER

    def __init__(self):
        self.calls = []
        self.failure = None

    def search(self, owner, **kwargs):
        self.calls.append((owner, kwargs))
        if self.failure:
            raise self.failure
        return DrivePage((FILE,), "next-token", True)

    def get_metadata(self, owner, file_id):
        self.calls.append((owner, file_id))
        if self.failure:
            raise self.failure
        return FILE


@pytest.fixture
def harness():
    reader = Reader()
    server = MCPServer(
        "PAM test",
        tools=[
            create_calendar_tool(fake_service()),
            *create_drive_tools(reader),
        ],
    )
    return server, reader


@pytest.mark.asyncio
async def test_discovery_publishes_exact_read_only_names_schemas_and_labels(harness):
    server, reader = harness
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "get_weekly_availability",
        "drive_search_files",
        "drive_get_file_metadata",
    }
    drive = {tool.name: tool for tool in tools if tool.name.startswith("drive_")}
    for tool in drive.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema["additionalProperties"] is False
        assert "untrusted" in tool.description
        assert "READ ONLY" in tool.description
        assert "owner" not in tool.input_schema["properties"]
    search = drive["drive_search_files"].input_schema["properties"]
    assert set(search) == {"name", "page_size", "page_token"}
    assert search["page_size"]["default"] == 10
    assert search["page_size"]["maximum"] == 50
    assert drive["drive_get_file_metadata"].input_schema["required"] == ["file_id"]
    assert reader.calls == []


@pytest.mark.parametrize(
    "tool,args",
    [
        ("drive_search_files", {"owner": "private-owner"}),
        ("drive_search_files", {"name": " "}),
        ("drive_search_files", {"name": "x" * 201}),
        ("drive_search_files", {"name": "line\nbreak"}),
        ("drive_search_files", {"page_size": 0}),
        ("drive_search_files", {"page_size": 51}),
        ("drive_search_files", {"page_size": True}),
        ("drive_search_files", {"page_size": "10"}),
        ("drive_search_files", {"page_token": "invalid token"}),
        ("drive_search_files", {"credentials": "PRIVATE-TOKEN"}),
        ("drive_get_file_metadata", {}),
        ("drive_get_file_metadata", {"file_id": "../secret"}),
        ("drive_get_file_metadata", {"file_id": "https://evil.test"}),
        ("drive_get_file_metadata", {"file_id": 123}),
        ("drive_get_file_metadata", {"file_id": "valid", "url": "PRIVATE-URL"}),
    ],
)
@pytest.mark.asyncio
async def test_invalid_inputs_do_not_reach_reader_or_echo_values(harness, tool, args):
    server, reader = harness
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    assert "PRIVATE" not in str(result.content)
    assert "private-owner" not in str(result.content)
    assert reader.calls == []


@pytest.mark.asyncio
async def test_valid_results_bind_configured_owner_and_keep_untrusted_provenance(
    harness,
):
    server, reader = harness
    async with Client(server) as client:
        search = await client.call_tool("drive_search_files", {"name": "PAM TEST"})
        metadata = await client.call_tool(
            "drive_get_file_metadata", {"file_id": "test-file"}
        )
    assert search.is_error is False and metadata.is_error is False
    assert reader.calls == [
        (OWNER, {"name": "PAM TEST", "page_size": 10, "page_token": None}),
        (OWNER, "test-file"),
    ]
    for result in (search, metadata):
        data = result.structured_content
        assert data["source"] == "google_drive" and data["data_kind"] == "metadata"
        assert data["untrusted"] is True and data["error"] is None
        assert data["files"][0]["name"] == FILE.name
        assert "owner" not in data and "credentials" not in data
    assert search.structured_content["next_page_token"] == "next-token"
    assert search.structured_content["incomplete_search"] is True
    assert metadata.structured_content["next_page_token"] is None


@pytest.mark.asyncio
async def test_literal_null_strings_are_not_coerced_to_unbounded_listing(harness):
    server, reader = harness
    async with Client(server) as client:
        result = await client.call_tool(
            "drive_search_files", {"name": "null", "page_token": "null"}
        )
    assert not result.is_error
    assert reader.calls[0][1]["name"] == "null"
    assert reader.calls[0][1]["page_token"] == "null"


@pytest.mark.parametrize(
    "code",
    [
        "consent_required",
        "reconnect_required",
        "unavailable",
        "invalid_page_token",
        "rate_limited",
        "temporary_failure",
        "invalid_response",
        "invalid_request",
    ],
)
@pytest.mark.asyncio
async def test_runtime_errors_use_structured_safe_error_and_mcp_error_flag(
    harness, code
):
    server, reader = harness
    reader.failure = DriveReadError(code)
    async with Client(server) as client:
        result = await client.call_tool("drive_search_files", {})
    assert result.is_error
    data = result.structured_content
    assert data["error"] == {
        "code": code,
        "message": str(reader.failure),
        "retryable": reader.failure.retryable,
    }
    assert data["files"] == [] and data["untrusted"] is True


@pytest.mark.asyncio
async def test_unexpected_drive_failure_is_hidden_and_calendar_still_works(
    harness, caplog
):
    server, reader = harness
    reader.failure = RuntimeError("PRIVATE-REFRESH-TOKEN")
    async with Client(server) as client:
        drive = await client.call_tool("drive_search_files", {})
        calendar = await client.call_tool("get_weekly_availability", REQUEST)
    assert drive.is_error and not calendar.is_error
    assert drive.structured_content["error"]["code"] == "temporary_failure"
    assert "PRIVATE" not in str(drive.content) + caplog.text


@pytest.mark.asyncio
async def test_calendar_failure_does_not_block_drive():
    reader = Reader()
    server = MCPServer(
        "PAM test",
        tools=[
            create_calendar_tool(AvailabilityService(FailingReader())),
            *create_drive_tools(reader),
        ],
    )
    async with Client(server) as client:
        calendar = await client.call_tool("get_weekly_availability", REQUEST)
        drive = await client.call_tool("drive_search_files", {})
    assert calendar.is_error and not drive.is_error


@pytest.mark.asyncio
async def test_existing_conversation_client_still_exposes_only_calendar(harness):
    server, _ = harness
    client = local_client_from_server(server)
    assert [tool.name for tool in await client.discover_tools()] == [
        "get_weekly_availability"
    ]
    assert "availability" in await client.get_weekly_availability(REQUEST)


@pytest.mark.asyncio
async def test_shared_server_registration_is_offline_with_fake_calendar(
    monkeypatch, tmp_path
):
    reader = Reader()
    settings = enabled_settings(drive_credential_storage_path=tmp_path / "missing.bin")
    monkeypatch.setattr(composition, "GoogleDriveReader", lambda auth: reader)
    server = composition.create_mcp_server(settings)
    assert len(await server.list_tools()) == 3
    assert reader.calls == []
    assert not settings.drive_credential_storage_path.exists()


@pytest.mark.parametrize(
    "argument,stdin,exit_code",
    [
        ("--list-tools", "", 0),
        ("--call-tool", '{"name":"PAM TEST"}', 0),
        ("--call-tool", '{"owner":"PRIVATE"}', 1),
    ],
)
def test_terminal_diagnostics_use_mcp_without_model_clients(
    harness, monkeypatch, capsys, argument, stdin, exit_code
):
    server, reader = harness
    monkeypatch.setattr(composition, "create_mcp_server", lambda: server)
    argv = ["pam", argument] + (
        ["drive_search_files"] if argument == "--call-tool" else []
    )
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as error:
        composition.main()
    assert error.value.code == exit_code
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    if argument == "--list-tools":
        assert "drive_search_files" in json.loads(output.out)
        assert reader.calls == []


@pytest.mark.parametrize(
    "stdin",
    ["not-json", "[]", "x" * 8193, "[" * 1500],
    ids=["bad-json", "array", "oversized", "deep-json"],
)
def test_terminal_bad_input_is_sanitized_before_construction(
    monkeypatch, capsys, stdin
):
    monkeypatch.setattr(sys, "argv", ["pam", "--call-tool", "drive_search_files"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(
        composition, "create_mcp_server", lambda: pytest.fail("must not construct")
    )
    with pytest.raises(SystemExit) as error:
        composition.main()
    assert error.value.code == 2
    assert "JSON argument object" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_real_reader_rechecks_consent_for_each_mcp_call(request):
    state = request.getfixturevalue("metadata_harness")
    server = MCPServer("PAM test", tools=create_drive_tools(state.reader))
    async with Client(server) as client:
        allowed = await client.call_tool("drive_search_files", {"name": "PAM TEST"})
        assert not allowed.is_error
        state.auth.set_permissions(
            allow_read=False,
            allow_metadata_transfer=False,
            confirmed_destination=None,
        )
        denied = await client.call_tool(
            "drive_get_file_metadata", {"file_id": "test-file_1"}
        )
    assert denied.is_error
    assert denied.structured_content["error"]["code"] == "consent_required"
    assert len(state.calls) == len(state.refreshes) == 1


@pytest.mark.asyncio
async def test_stdio_discovers_both_families_without_live_google_credentials(tmp_path):
    from cryptography.fernet import Fernet

    launch = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pam.mcp.server"],
        cwd=Path(__file__).parents[2],
        env={
            **os.environ,
            "PAM_DRIVE_ENABLED": "true",
            "PAM_CALENDAR_BACKEND": "fake",
            "PAM_MODEL_PROVIDER": "fake",
            "PAM_MEMORY_BACKEND": "disabled",
            "PAM_TELEGRAM_ENABLED": "false",
            "PAM_ENVIRONMENT": "development",
            "PAM_APP_SECRET": "x" * 48,
            "PAM_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "PAM_DRIVE_GOOGLE_CLIENT_ID": "test-drive-client",
            "PAM_DRIVE_GOOGLE_CLIENT_SECRET": "test-drive-secret",
            "PAM_DRIVE_GOOGLE_ACCOUNT_EMAIL": "owner@example.test",
            "PAM_DRIVE_GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/oauth/google/drive/callback",
            "PAM_DRIVE_OWNER_ID": "test-owner",
            "PAM_DRIVE_CREDENTIAL_STORAGE_PATH": str(tmp_path / "missing-drive.bin"),
        },
    )
    async with Client(launch) as client:
        tools = await client.list_tools()
        denied = await client.call_tool("drive_search_files", {"name": "PAM TEST"})
        calendar = await client.call_tool("get_weekly_availability", REQUEST)
    assert {tool.name for tool in tools.tools} == {
        "get_weekly_availability",
        "drive_search_files",
        "drive_get_file_metadata",
    }
    assert denied.is_error
    assert denied.structured_content["error"]["code"] == "reconnect_required"
    assert not calendar.is_error


def test_terminal_configuration_failure_never_echoes_settings(monkeypatch, capsys):

    def invalid():
        raise ValueError("PRIVATE-SECRET")

    monkeypatch.setattr(composition, "create_mcp_server", invalid)
    monkeypatch.setattr(sys, "argv", ["pam", "--list-tools"])
    with pytest.raises(SystemExit) as error:
        composition.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.err == "Invalid PAM configuration. Check your settings.\n"
    assert output.out == ""
