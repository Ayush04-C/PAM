"""Offline Stage 4 authorization, credential and operator-boundary tests."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from pydantic import ValidationError

from pam.api.drive_oauth import create_drive_oauth_router
from pam.api.google_oauth import InMemoryOAuthStateStore
from pam.config import Settings
from pam.conversation.factory import configured_model_destination
from pam.integrations import drive_auth
from pam.integrations.drive_auth import (
    DRIVE_SCOPES,
    DriveAuthorization,
    DriveAuthorizationError,
)
from pam.integrations.google_calendar import (
    GOOGLE_CALENDAR_SCOPES,
    GoogleOAuthClient,
    GoogleOAuthConfig,
)
from pam.memory.models import MemoryOwnerId
from pam.security.credentials import (
    CredentialDecryptionError,
    EncryptedFileCredentialStore,
)

SECRET = "operator-secret-" + "x" * 40
OWNER = MemoryOwnerId("cli-local")
DESTINATION = "test-model:destination"
TOKEN = "PRIVATE-REFRESH-TOKEN"
HEADERS = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in os.environ:
        if name.startswith("PAM_"):
            monkeypatch.delenv(name)


def enabled_settings(**overrides):
    values = dict(
        _env_file=None,
        drive_enabled=True,
        drive_google_client_id="drive-client",
        drive_google_client_secret="client-secret",
        drive_owner_id="cli-local",
        drive_google_account_email="owner@example.test",
        app_secret=SECRET,
        credential_encryption_key=Fernet.generate_key().decode(),
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def authorization(tmp_path, monkeypatch):
    service = DriveAuthorization(
        GoogleOAuthConfig(
            "drive-client",
            "private-client-secret",
            "http://127.0.0.1:8000/oauth/google/drive/callback",
        ),
        EncryptedFileCredentialStore(
            tmp_path / "drive.bin", Fernet.generate_key().decode()
        ),
        owner=OWNER,
        account_email="owner@example.test",
        model_destination=DESTINATION,
    )
    credentials = SimpleNamespace(refresh_token=TOKEN, granted_scopes=DRIVE_SCOPES)
    monkeypatch.setattr(service.oauth, "exchange_credentials", lambda *_: credentials)
    monkeypatch.setattr(
        service, "_account", lambda _: ("owner@example.test", "account-id")
    )
    return service


def connect(service):
    service.connect("private-code", "verifier")


def make_client(service, states=None, address="127.0.0.1"):
    app = FastAPI()
    app.include_router(create_drive_oauth_router(service, SECRET, states))
    return TestClient(app, base_url="http://127.0.0.1:8000", client=(address, 5000))


def test_drive_disabled_requires_no_secrets():
    assert Settings(_env_file=None).drive_enabled is False


@pytest.mark.parametrize(
    "field",
    [
        "drive_google_client_id",
        "drive_google_client_secret",
        "drive_owner_id",
        "drive_google_account_email",
        "credential_encryption_key",
        "app_secret",
    ],
)
def test_enabled_drive_requires_operator_and_oauth_configuration(field):
    with pytest.raises(ValidationError):
        enabled_settings(**{field: None})


@pytest.mark.parametrize(
    "redirect",
    [
        "https://external.test/oauth/google/drive/callback",
        "http://localhost:8000/oauth/google/drive/callback",
        "http://127.0.0.1:8000/wrong",
        "http://127.0.0.1:8000/oauth/google/drive/callback?x=1",
        "http://user@127.0.0.1:8000/oauth/google/drive/callback",
    ],
)
def test_redirect_is_fixed_to_loopback_callback(redirect):
    with pytest.raises(ValidationError):
        enabled_settings(drive_google_redirect_uri=redirect)


def test_drive_enabled_with_fake_calendar():
    assert enabled_settings().calendar_backend == "fake"
    with pytest.raises(ValidationError):
        enabled_settings(app_secret="short")


def test_atomic_write_failure_preserves_previous_token(tmp_path, monkeypatch):
    path = tmp_path / "credential.bin"
    store = EncryptedFileCredentialStore(path, Fernet.generate_key().decode())
    store.save("old-token")

    def fail(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save("replacement-token")
    assert store.load() == "old-token"
    assert list(tmp_path.iterdir()) == [path]


def test_shared_oauth_preserves_calendar_and_separates_drive_scopes(monkeypatch):
    calls = []

    class FakeFlow:
        @classmethod
        def from_client_config(cls, config, **kwargs):
            calls.append(kwargs)
            return cls()

        def authorization_url(self, **kwargs):
            calls.append(kwargs)
            return "https://accounts.google.com/example", None

    monkeypatch.setattr("pam.integrations.google_calendar.Flow", FakeFlow)
    config = GoogleOAuthConfig("client", "secret", "http://127.0.0.1/callback")
    GoogleOAuthClient(config).authorization_url("state", "verifier")
    assert calls[0]["scopes"] == list(GOOGLE_CALENDAR_SCOPES)
    assert calls[1]["include_granted_scopes"] == "true"
    GoogleOAuthClient(
        config, scopes=DRIVE_SCOPES, include_granted_scopes=False
    ).authorization_url("state", "verifier")
    assert calls[2]["scopes"] == list(DRIVE_SCOPES)
    assert calls[3]["include_granted_scopes"] == "false"
    assert calls[3]["access_type"] == "offline"


def test_state_expiry_capacity_replay_and_capability_isolation():
    now = [100.0]
    states = InMemoryOAuthStateStore(ttl_seconds=10, capacity=1, clock=lambda: now[0])
    first = states.create("verifier")
    with pytest.raises(ValueError):
        states.create("extra")
    assert InMemoryOAuthStateStore().consume(first) is None
    now[0] = 110
    assert states.consume(first) is None
    second = states.create("second")
    assert states.consume(second) == "second"
    assert states.consume(second) is None


def test_connect_encrypts_account_grant_and_defaults_transfer_off(authorization):
    connect(authorization)
    grant = authorization.load()
    assert grant.refresh_token.get_secret_value() == TOKEN
    assert TOKEN.encode() not in authorization.store._path.read_bytes()
    assert TOKEN not in repr(grant)
    consent = authorization.consent(OWNER)
    assert consent.allow_read and not consent.allow_metadata_transfer
    assert not consent.allow_content_transfer


@pytest.mark.parametrize(
    "scopes", [None, (), ("write-scope",), (*DRIVE_SCOPES, "extra")]
)
def test_partial_unknown_or_excess_scopes_preserve_saved_grant(
    authorization, monkeypatch, scopes
):
    connect(authorization)
    previous = authorization.store._path.read_bytes()
    monkeypatch.setattr(
        authorization.oauth,
        "exchange_credentials",
        lambda *_: SimpleNamespace(refresh_token="new", granted_scopes=scopes),
    )
    with pytest.raises(DriveAuthorizationError, match="exactly metadata"):
        connect(authorization)
    assert authorization.store._path.read_bytes() == previous


def test_wrong_account_preserves_saved_grant(authorization, monkeypatch):
    connect(authorization)
    previous = authorization.store._path.read_bytes()
    monkeypatch.setattr(
        authorization, "_account", lambda _: ("wrong@example.test", "other")
    )
    with pytest.raises(DriveAuthorizationError, match="Wrong Google account"):
        connect(authorization)
    assert authorization.store._path.read_bytes() == previous


def test_missing_refresh_requires_existing_verified_same_account(
    authorization, monkeypatch
):
    monkeypatch.setattr(
        authorization.oauth,
        "exchange_credentials",
        lambda *_: SimpleNamespace(refresh_token=None, granted_scopes=DRIVE_SCOPES),
    )
    with pytest.raises(DriveAuthorizationError, match="not connected"):
        connect(authorization)
    monkeypatch.setattr(
        authorization.oauth,
        "exchange_credentials",
        lambda *_: SimpleNamespace(refresh_token=TOKEN, granted_scopes=DRIVE_SCOPES),
    )
    connect(authorization)
    monkeypatch.setattr(
        authorization.oauth,
        "exchange_credentials",
        lambda *_: SimpleNamespace(refresh_token=None, granted_scopes=DRIVE_SCOPES),
    )
    checked = []
    monkeypatch.setattr(authorization, "check_connection", lambda: checked.append(True))
    connect(authorization)
    assert checked == [True]
    assert authorization.load().refresh_token.get_secret_value() == TOKEN


def test_permissions_owner_destination_revoke_and_disconnect(authorization):
    connect(authorization)
    with pytest.raises(DriveAuthorizationError):
        authorization.set_permissions(
            allow_read=True, allow_metadata_transfer=True, confirmed_destination="wrong"
        )
    authorization.set_permissions(
        allow_read=True, allow_metadata_transfer=True, confirmed_destination=DESTINATION
    )
    assert authorization.consent(OWNER).allow_metadata_transfer
    with pytest.raises(DriveAuthorizationError):
        authorization.consent(MemoryOwnerId("other"))
    authorization.model_destination = "changed-provider"
    assert not authorization.consent(OWNER).allow_metadata_transfer
    authorization.set_permissions(
        allow_read=False, allow_metadata_transfer=False, confirmed_destination=None
    )
    assert not authorization.consent(OWNER).allow_read
    authorization.disconnect()
    with pytest.raises(DriveAuthorizationError):
        authorization.load()


def test_changed_owner_client_account_and_corruption_fail_closed(authorization):
    connect(authorization)
    authorization.owner = MemoryOwnerId("other")
    with pytest.raises(DriveAuthorizationError):
        authorization.load()
    authorization.owner = OWNER
    authorization.config = replace(authorization.config, client_id="changed")
    with pytest.raises(DriveAuthorizationError):
        authorization.load()
    authorization.store.save("not-json")
    with pytest.raises(DriveAuthorizationError):
        authorization.load()


def test_wrong_encryption_key_fails(authorization):
    connect(authorization)
    wrong = EncryptedFileCredentialStore(
        authorization.store._path, Fernet.generate_key().decode()
    )
    with pytest.raises(CredentialDecryptionError):
        wrong.load()


@pytest.mark.parametrize("failure", [None, "revoked", "transient", "scope", "account"])
def test_refresh_uses_drive_scope_and_fixed_timeouts(
    authorization, monkeypatch, failure
):
    connect(authorization)
    calls = []

    class FakeCredentials:
        granted_scopes = DRIVE_SCOPES if failure != "scope" else ("wrong",)

        def __init__(self, **kwargs):
            calls.append(kwargs)

        def refresh(self, request):
            assert request.keywords["timeout"] == 20
            if failure in {"revoked", "transient"}:
                raise RefreshError("PRIVATE ERROR", retryable=failure == "transient")

    monkeypatch.setattr(drive_auth, "Credentials", FakeCredentials)
    if failure == "account":
        monkeypatch.setattr(authorization, "_account", lambda _: ("wrong", "wrong"))
    if failure:
        with pytest.raises(RuntimeError):
            authorization.check_connection()
    else:
        authorization.check_connection()
    assert calls[0]["scopes"] == list(DRIVE_SCOPES)
    assert calls[0]["client_id"] == "drive-client"


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/start"),
        ("get", "/status"),
        ("post", "/permissions"),
        ("post", "/check"),
        ("post", "/disconnect"),
    ],
)
def test_operator_required_for_every_management_endpoint(authorization, method, path):
    client = make_client(authorization)
    assert client.request(method, "/oauth/google/drive" + path).status_code == 401


@pytest.mark.parametrize(
    "headers,address",
    [
        ({"Host": "evil.example"}, "127.0.0.1"),
        ({"Origin": "https://evil.example"}, "127.0.0.1"),
        ({}, "192.0.2.1"),
    ],
)
def test_remote_host_and_cross_origin_denied(authorization, headers, address):
    client = make_client(authorization, address=address)
    assert (
        client.post("/oauth/google/drive/start", headers=HEADERS | headers).status_code
        == 403
    )


def test_callback_state_denial_replay_and_success(authorization, monkeypatch, caplog):
    states = InMemoryOAuthStateStore()
    monkeypatch.setattr(
        authorization.oauth,
        "authorization_url",
        lambda state, _: f"https://accounts.google.com/test?state={state}",
    )
    client = make_client(authorization, states)
    response = client.post("/oauth/google/drive/start", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    state = response.json()["authorization_url"].split("state=")[1]
    result = client.get(
        "/oauth/google/drive/callback", params={"state": state, "code": "secret-code"}
    )
    assert result.json() == {"status": "connected", "model_transfer": "not authorized"}
    assert (
        client.get(
            "/oauth/google/drive/callback",
            params={"state": state, "code": "secret-code"},
        ).status_code
        == 400
    )
    denied_state = states.create("verifier")
    assert (
        client.get(
            "/oauth/google/drive/callback",
            params={"state": denied_state, "error": "access_denied"},
        ).status_code
        == 400
    )
    assert states.consume(denied_state) is None
    assert "secret-code" not in result.text + caplog.text
    assert TOKEN not in result.text + caplog.text


def test_management_status_permissions_check_and_disconnect(authorization, monkeypatch):
    connect(authorization)
    client = make_client(authorization)
    before = client.get("/oauth/google/drive/status", headers=HEADERS)
    assert before.json()["allow_metadata_transfer"] is False
    assert TOKEN not in before.text and "owner@example.test" not in before.text
    payload = {
        "allow_read": True,
        "allow_metadata_transfer": True,
        "confirmed_destination": DESTINATION,
    }
    assert (
        client.post(
            "/oauth/google/drive/permissions", headers=HEADERS, json=payload
        ).status_code
        == 200
    )
    assert authorization.consent(OWNER).allow_metadata_transfer
    payload["allow_metadata_transfer"] = "true"
    assert (
        client.post(
            "/oauth/google/drive/permissions", headers=HEADERS, json=payload
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/oauth/google/drive/permissions",
            headers=HEADERS,
            json={"allow_content_transfer": True},
        ).status_code
        == 400
    )
    monkeypatch.setattr(authorization, "check_connection", lambda: None)
    assert (
        client.post("/oauth/google/drive/check", headers=HEADERS).json()["status"]
        == "refresh and account verified"
    )
    assert (
        client.post("/oauth/google/drive/disconnect", headers=HEADERS).status_code
        == 200
    )
    assert not authorization.store._path.exists()


def test_transport_failure_hides_raw_error_and_preserves_credentials(
    authorization, monkeypatch
):
    connect(authorization)
    previous = authorization.store._path.read_bytes()
    states = InMemoryOAuthStateStore()
    state = states.create("verifier")

    def fail(*args):
        raise RuntimeError("private-token-and-account")

    monkeypatch.setattr(authorization.oauth, "exchange_credentials", fail)
    response = make_client(authorization, states).get(
        "/oauth/google/drive/callback", params={"state": state, "code": "code"}
    )
    assert response.status_code == 503
    assert "private-token" not in response.text
    assert authorization.store._path.read_bytes() == previous


def test_disconnect_invalidates_pending_callback(authorization):
    states = InMemoryOAuthStateStore()
    state = states.create("verifier")
    client = make_client(authorization, states)
    assert (
        client.post("/oauth/google/drive/disconnect", headers=HEADERS).status_code
        == 200
    )
    assert (
        client.get(
            "/oauth/google/drive/callback", params={"state": state, "code": "code"}
        ).status_code
        == 400
    )


def test_app_registers_drive_only_when_enabled_without_touching_calendar(tmp_path):
    from pam.main import create_app

    calendar_path = tmp_path / "calendar.bin"
    calendar_path.write_bytes(b"existing-calendar-credential")
    drive_path = tmp_path / "drive.bin"
    settings = enabled_settings(
        credential_storage_path=calendar_path, drive_credential_storage_path=drive_path
    )
    app = create_app(settings=settings)
    client = TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 5000)
    )
    assert client.get("/health").status_code == 200
    assert client.get("/oauth/google/drive/status").status_code == 401
    assert not drive_path.exists()
    assert calendar_path.read_bytes() == b"existing-calendar-credential"
    disabled = create_app(settings=Settings(_env_file=None))
    assert TestClient(disabled).post("/oauth/google/drive/start").status_code == 404


def test_destination_matches_provider_identity_without_clients():
    settings = enabled_settings(
        model_provider="bharatcode",
        bharatcode_api_key="key",
        bharatcode_base_url="https://example.test/v1/",
    )
    assert (
        configured_model_destination(settings)
        == "bharatcode:https://example.test/v1|deepseek-v4.1-flash"
    )
    assert configured_model_destination(Settings(_env_file=None)) is None


def test_identity_request_is_bounded_and_uses_only_account_fields(monkeypatch):
    calls = []

    class Session:
        def __init__(self, credentials, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "user": {"emailAddress": "Owner@Example.test", "permissionId": "id"}
                },
            )

    monkeypatch.setattr(drive_auth, "AuthorizedSession", Session)
    assert DriveAuthorization._account(object()) == ("owner@example.test", "id")
    assert calls[0] == {"refresh_timeout": 20}
    assert calls[1] == (
        "https://www.googleapis.com/drive/v3/about",
        {"params": {"fields": "user(emailAddress,permissionId)"}, "timeout": 20},
    )


def test_drive_connect_does_not_change_calendar_token_or_routes(authorization):
    from pam.api.google_oauth import create_google_oauth_router
    from pam.tests.test_google_calendar import FakeOAuthClient, MemoryCredentialStore

    calendar_store = MemoryCredentialStore()
    calendar_store.save("existing-calendar-token")
    calendar_oauth = FakeOAuthClient()
    app = FastAPI()
    app.include_router(
        create_google_oauth_router(
            calendar_oauth, InMemoryOAuthStateStore(), calendar_store
        )
    )
    states = InMemoryOAuthStateStore()
    app.include_router(create_drive_oauth_router(authorization, SECRET, states))
    client = TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 5000)
    )
    assert client.get("/oauth/google/start", follow_redirects=False).status_code == 307
    drive_state = states.create("drive-verifier")
    assert (
        client.get(
            "/oauth/google/drive/callback",
            params={"state": drive_state, "code": "drive-code"},
        ).status_code
        == 200
    )
    assert calendar_store.load() == "existing-calendar-token"
    assert (
        client.get(
            "/oauth/google/callback",
            params={"state": calendar_oauth.state, "code": "calendar-code"},
        ).status_code
        == 200
    )
    assert authorization.load().refresh_token.get_secret_value() == TOKEN


@pytest.mark.parametrize(
    "field,value",
    [
        ("drive_google_client_secret", " "),
        ("drive_owner_id", " "),
        ("credential_encryption_key", "invalid-key"),
    ],
)
def test_invalid_operator_values_fail_settings_validation(field, value):
    with pytest.raises(ValidationError):
        enabled_settings(**{field: value})


def test_http_startup_hides_configuration_validation_inputs(monkeypatch, tmp_path):
    import traceback

    from pam.main import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAM_DRIVE_ENABLED", "true")
    monkeypatch.setenv("PAM_DRIVE_GOOGLE_CLIENT_SECRET", "DO-NOT-PRINT-THIS-SECRET")
    with pytest.raises(RuntimeError, match="Invalid PAM configuration") as error:
        create_app()
    rendered = "".join(traceback.format_exception(error.value))
    assert "DO-NOT-PRINT-THIS-SECRET" not in rendered
