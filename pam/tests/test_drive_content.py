"""Stage 9 offline content reads, scope profiles and strict MCP validation."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server import MCPServer

from pam.conversation.mcp_client import (
    DRIVE_CONTENT_TOOL,
    LocalDriveMcpClient,
    McpUnavailable,
)
from pam.integrations import drive_auth, google_drive
from pam.integrations.drive_auth import (
    DRIVE_CONTENT_SCOPE,
    DRIVE_SCOPES,
    DriveAuthorization,
    DriveAuthorizationError,
)
from pam.integrations.google_drive import DriveReadError, content_passages
from pam.mcp.driver import create_drive_tools
from pam.tests.test_drive_metadata import FILE, OWNER, Response
from pam.tests.test_drive_metadata import harness as metadata_harness  # noqa: F401
from pam.tests.test_drive_oauth import HEADERS, make_client


@pytest.fixture
def content_state(request, monkeypatch):
    h = request.getfixturevalue("metadata_harness")
    old = h.auth
    h.auth = DriveAuthorization(
        old.config,
        old.store,
        owner=old.owner,
        account_email=old.account_email,
        model_destination=old.model_destination,
        content_enabled=True,
    )
    h.auth._save(h.auth.load().model_copy(update={"scopes": (DRIVE_CONTENT_SCOPE,)}))
    h.reader = google_drive.GoogleDriveReader(h.auth)
    h.details = FILE | {"size": "12", "capabilities": {"canDownload": True}}
    h.raw = b"Hello world!"
    h.status = 200
    h.responses = []
    h.after_get = lambda: None

    class Credentials:
        granted_scopes = (DRIVE_CONTENT_SCOPE,)

        def __init__(self, **kwargs):
            h.refreshes.append(kwargs)

        def refresh(self, request):
            pass

    class Session:
        def __init__(self, *args, **kwargs):
            assert kwargs["max_refresh_attempts"] == 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            h.calls.append((url, kwargs))
            assert kwargs["stream"] and not kwargs["allow_redirects"]
            response = (
                Response(
                    {"files": [h.details]} if url.endswith("/files") else h.details
                )
                if "fields" in kwargs["params"]
                else Response(None, status=h.status, raw=h.raw)
            )
            h.responses.append(response)
            h.after_get()
            return response

    monkeypatch.setattr(drive_auth, "Credentials", Credentials)
    monkeypatch.setattr(google_drive, "AuthorizedSession", Session)
    return h


@pytest.mark.parametrize("mime", ["text/plain", "application/vnd.google-apps.document"])
def test_supported_content_uses_current_metadata_and_fixed_google_endpoint(
    content_state, mime
):
    h = content_state
    h.details["mimeType"] = mime
    result = h.reader.get_content(OWNER, FILE["id"])
    assert result.passages == ("Hello world!",)
    assert len(h.calls) == 2 and all(r.closed for r in h.responses)
    assert h.calls[1][1]["params"] == (
        {"alt": "media"} if mime == "text/plain" else {"mimeType": "text/plain"}
    )
    assert h.calls[1][0].endswith("/export") == (mime != "text/plain")
    assert "Hello" not in repr(result)


@pytest.mark.parametrize(
    "mime",
    [
        "application/pdf",
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.shortcut",
        "image/png",
    ],
)
def test_unsupported_formats_never_download(content_state, mime):
    h = content_state
    h.details["mimeType"] = mime
    with pytest.raises(DriveReadError, match="supported"):
        h.reader.get_content(OWNER, FILE["id"])
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"capabilities": {}}, "download_denied"),
        ({"capabilities": {"canDownload": False}}, "download_denied"),
        ({"size": None}, "invalid_response"),
        ({"size": "huge"}, "invalid_response"),
        ({"size": str(256 * 1024 + 1)}, "content_too_large"),
        ({"trashed": True}, "unavailable"),
        ({"driveId": "shared"}, "unavailable"),
        ({"id": "different"}, "invalid_response"),
    ],
)
def test_content_preflight_failures_do_not_download(content_state, changes, code):
    h = content_state
    h.details.update(changes)
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == code and len(h.calls) == 1


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "invalid_content"),
        (b" \n", "invalid_content"),
        (b"\xff", "invalid_content"),
        (b"a\x00b", "invalid_content"),
        (b"x" * 12001, "content_too_large"),
        (b"x" * (256 * 1024 + 1), "content_too_large"),
    ],
    ids=["empty", "blank", "encoding", "binary", "character-limit", "byte-limit"],
)
def test_invalid_or_oversized_download_is_closed_without_partial_text(
    content_state, raw, code
):
    h = content_state
    h.raw = raw
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == code and all(r.closed for r in h.responses)


def test_passage_boundaries_bom_and_display_controls():
    assert content_passages(b"\xef\xbb\xbfHi\n\tthere") == ("Hi\n\tthere",)
    assert content_passages("Hi\u202e\x07there".encode()) == ("Hithere",)
    assert [len(p) for p in content_passages(b"x" * 12000)] == [1000] * 12


@pytest.mark.parametrize(
    "mode", ["disabled", "metadata_scope", "wrong_owner", "revoked_read"]
)
def test_content_authorization_fails_before_any_network(content_state, mode):
    h = content_state
    owner = OWNER
    if mode == "disabled":
        h.auth.content_enabled = False
    elif mode == "metadata_scope":
        h.auth._save(h.auth.load().model_copy(update={"scopes": DRIVE_SCOPES}))
    elif mode == "wrong_owner":
        owner = replace(OWNER, value="other")
    else:
        h.auth._save(h.auth.load().model_copy(update={"allow_read": False}))
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(owner, FILE["id"])
    assert error.value.code == "consent_required"
    assert h.calls == h.refreshes == []


def test_revocation_between_preflight_and_download_stops_second_request(content_state):
    h = content_state
    h.after_get = lambda: h.auth._save(
        h.auth.load().model_copy(update={"allow_read": False})
    )
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == "consent_required" and len(h.calls) == 1


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "unavailable"),
        (404, "unavailable"),
        (429, "rate_limited"),
        (500, "temporary_failure"),
        (302, "temporary_failure"),
    ],
)
def test_content_http_failures_are_fixed_safe_errors(content_state, status, code):
    h = content_state
    h.status, h.raw = status, b"PRIVATE-ERROR-BODY"
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == code and "PRIVATE" not in str(error.value)


def test_permissions_endpoint_requires_content_scope_and_explicit_destination(
    content_state,
):
    h = content_state
    client = make_client(h.auth)
    values = {
        "allow_read": True,
        "allow_metadata_transfer": True,
        "allow_content_transfer": True,
        "confirmed_destination": h.auth.model_destination,
    }
    assert (
        client.post(
            "/oauth/google/drive/permissions", headers=HEADERS, json=values
        ).status_code
        == 200
    )
    assert client.get("/oauth/google/drive/status", headers=HEADERS).json()[
        "allow_content_transfer"
    ]
    assert (
        client.post("/oauth/google/drive/permissions", json=values).status_code == 401
    )
    values["confirmed_destination"] = "other"
    assert (
        client.post(
            "/oauth/google/drive/permissions", headers=HEADERS, json=values
        ).status_code
        == 400
    )
    values.update(
        confirmed_destination=h.auth.model_destination, allow_metadata_transfer=False
    )
    assert (
        client.post(
            "/oauth/google/drive/permissions", headers=HEADERS, json=values
        ).status_code
        == 400
    )


def test_metadata_only_grants_remain_loadable_but_cannot_gain_content_transfer(
    content_state,
):
    h = content_state
    h.auth._save(h.auth.load().model_copy(update={"scopes": DRIVE_SCOPES}))
    h.auth.set_permissions(
        allow_read=True,
        allow_metadata_transfer=True,
        confirmed_destination=h.auth.model_destination,
    )
    with pytest.raises(DriveAuthorizationError):
        h.auth.set_permissions(
            allow_read=True,
            allow_metadata_transfer=True,
            allow_content_transfer=True,
            confirmed_destination=h.auth.model_destination,
        )
    assert not h.auth.consent(OWNER).allow_content_transfer


def test_content_oauth_upgrade_requires_new_refresh_and_resets_transfer(
    content_state, monkeypatch
):
    h = content_state
    credentials = SimpleNamespace(
        refresh_token="new-token", granted_scopes=(DRIVE_CONTENT_SCOPE,)
    )
    monkeypatch.setattr(h.auth.oauth, "exchange_credentials", lambda *_: credentials)
    monkeypatch.setattr(h.auth, "_account", lambda _: (h.auth.account_email, "id"))
    h.auth.connect("code", "verifier")
    assert not h.auth.consent(OWNER).allow_content_transfer
    assert h.auth.load().refresh_token.get_secret_value() == "new-token"
    h.auth._save(h.auth.load().model_copy(update={"scopes": DRIVE_SCOPES}))
    previous = h.auth.store._path.read_bytes()
    credentials.refresh_token = None
    with pytest.raises(DriveAuthorizationError, match="new refresh"):
        h.auth.connect("code", "verifier")
    assert h.auth.store._path.read_bytes() == previous


@pytest.mark.asyncio
async def test_real_content_reader_mcp_and_narrow_client_work_together(content_state):
    h = content_state
    server = MCPServer(
        "Content test", tools=create_drive_tools(h.reader, content_enabled=True)
    )
    client = LocalDriveMcpClient(server, OWNER, content_enabled=True)
    assert DRIVE_CONTENT_TOOL in {t.name for t in await client.discover_tools()}
    result = await client.call_tool(DRIVE_CONTENT_TOOL, {"file_id": FILE["id"]}, OWNER)
    assert result["data_kind"] == "content" and result["passages"] == [
        {"label": "P1", "text": "Hello world!"}
    ]
    async with Client(server) as raw:
        invalid = await raw.call_tool(
            DRIVE_CONTENT_TOOL, {"file_id": FILE["id"], "url": "https://evil.test"}
        )
        assert invalid.is_error
    assert len(h.calls) == 2
    with pytest.raises(McpUnavailable):
        await LocalDriveMcpClient(server, OWNER).call_tool(
            DRIVE_CONTENT_TOOL, {"file_id": FILE["id"]}, OWNER
        )


@pytest.mark.asyncio
async def test_content_discovery_disabled_by_default(content_state):
    server = MCPServer("Metadata test", tools=create_drive_tools(content_state.reader))
    async with Client(server) as client:
        assert DRIVE_CONTENT_TOOL not in {
            t.name for t in (await client.list_tools()).tools
        }


def test_stream_stops_at_byte_cap_without_consuming_remaining_content(
    content_state, monkeypatch
):
    h = content_state
    original = Response.iter_content
    consumed = []

    def chunks(response, chunk_size):
        if response.payload is not None:
            yield from original(response, chunk_size)
        else:
            for i in range(100):
                consumed.append(i)
                yield b"x" * chunk_size

    monkeypatch.setattr(Response, "iter_content", chunks)
    with pytest.raises(DriveReadError) as error:
        h.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == "content_too_large"
    assert len(consumed) == 17 and all(r.closed for r in h.responses)


def test_slow_content_stream_fails_safely_and_closes(content_state, monkeypatch):
    moments = iter([0, 0, 0, 21])
    monkeypatch.setattr(google_drive, "monotonic", lambda: next(moments))
    with pytest.raises(DriveReadError) as error:
        content_state.reader.get_content(OWNER, FILE["id"])
    assert error.value.code == "temporary_failure"
    assert all(r.closed for r in content_state.responses)


def test_content_scope_profile_allows_only_known_read_only_scopes(content_state):
    h = content_state
    grant = h.auth.load()
    h.auth._save(
        grant.model_copy(update={"scopes": (DRIVE_CONTENT_SCOPE, *DRIVE_SCOPES)})
    )
    assert h.auth.load().scopes == (DRIVE_CONTENT_SCOPE, *DRIVE_SCOPES)
    h.auth._save(
        grant.model_copy(
            update={
                "scopes": (DRIVE_CONTENT_SCOPE, "https://www.googleapis.com/auth/drive")
            }
        )
    )
    with pytest.raises(DriveAuthorizationError):
        h.auth.load()


def test_oauth_requests_content_scope_only_when_explicitly_enabled(content_state):
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(
        urlsplit(content_state.auth.oauth.authorization_url("state", "verifier")).query
    )
    assert query["scope"] == [DRIVE_CONTENT_SCOPE]
    assert query["include_granted_scopes"] == ["false"]


@pytest.mark.asyncio
async def test_configuration_wires_content_only_when_enabled_without_google_io():
    from pam.integrations.google_wiring import create_drive_authorization
    from pam.mcp.server import create_mcp_server
    from pam.tests.test_drive_oauth import enabled_settings

    settings = enabled_settings(drive_content_enabled=True)
    auth = create_drive_authorization(settings)
    assert auth.content_enabled and auth.requested_scopes == (DRIVE_CONTENT_SCOPE,)
    async with Client(create_mcp_server(settings)) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {
        "get_weekly_availability",
        "drive_search_files",
        "drive_get_file_metadata",
        DRIVE_CONTENT_TOOL,
    }
    assert all(t.annotations.read_only_hint for t in tools)
