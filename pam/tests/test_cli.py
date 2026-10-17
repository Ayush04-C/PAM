"""Offline status diagnostics and CLI compatibility checks."""

import os

import pytest

from pam.config import Settings
from pam.conversation import cli
from pam.conversation.models import ModelDecision
from pam.conversation.provider import ScriptedModelProvider
from pam.tests.test_memory import NoCalendar


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    for name in os.environ:
        if name.startswith("PAM_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def unexpected_call(*args, **kwargs):
    pytest.fail("Offline status must not construct clients or start conversation")


def test_status_is_offline_and_exposes_only_approved_fields(monkeypatch, capsys):
    monkeypatch.setenv("PAM_MODEL_PROVIDER", "bharatcode")
    monkeypatch.setenv("PAM_BHARATCODE_API_KEY", "private-api-key")
    monkeypatch.setenv("PAM_BHARATCODE_BASE_URL", "https://private.example/token")
    monkeypatch.setenv("PAM_MEMORY_CLI_OWNER_ID", "private-owner")
    monkeypatch.setenv("PAM_DRIVE_CREDENTIAL_STORAGE_PATH", "private-drive.bin")
    monkeypatch.setenv("PAM_DRIVE_MAX_CONTEXT_CHARS", "500")
    monkeypatch.setattr("sys.argv", ["pam", "--status"])
    for name in (
        "create_model_provider",
        "create_mcp_server",
        "local_client_from_server",
        "create_memory_service",
        "ConversationService",
    ):
        monkeypatch.setattr(cli, name, unexpected_call)
    monkeypatch.setattr(cli.asyncio, "run", unexpected_call)
    monkeypatch.setattr("builtins.input", unexpected_call)
    cli.main()
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "Model provider: bharatcode\n"
        "Model configuration: present\n"
        "Calendar backend: fake\n"
        "Drive tools: not implemented\n"
        "Drive model-transfer consent: not collected by CLI\n"
        "Drive context limit: 500 characters\n"
        "Live connectivity: not checked\n"
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("PAM_DRIVE_MAX_CONTEXT_CHARS", "secret-invalid-limit"),
        ("PAM_MODEL_PROVIDER", "secret-provider"),
        ("PAM_TELEGRAM_ALLOWED_USER_IDS", "secret-user"),
        ("PAM_MODEL_PROVIDER", "bharatcode"),
    ],
)
def test_status_invalid_configuration_fails_without_echoing_input(
    monkeypatch, capsys, name, value
):
    monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["pam", "--status"])
    monkeypatch.setattr(cli, "create_model_provider", unexpected_call)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Invalid PAM configuration. Check your settings.\n"


@pytest.mark.asyncio
async def test_interactive_status_new_and_normal_turns(monkeypatch, capsys):
    settings = Settings(_env_file=None, drive_max_context_chars=123)
    provider = ScriptedModelProvider(
        [ModelDecision(text="First answer"), ModelDecision(text="Fresh answer")]
    )
    monkeypatch.setattr(cli, "create_model_provider", lambda _: provider)
    monkeypatch.setattr(cli, "create_mcp_server", lambda _: object())
    monkeypatch.setattr(cli, "local_client_from_server", lambda _: NoCalendar())
    services = []
    service_type = cli.ConversationService

    def capture_service(*args, **kwargs):
        assert kwargs["drive_max_context_chars"] == 123
        service = service_type(*args, **kwargs)
        services.append(service)
        return service

    monkeypatch.setattr(cli, "ConversationService", capture_service)
    messages = iter(["/status", "Hello", "/new", "Hello again", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    await cli.run(settings)
    output = capsys.readouterr().out
    assert cli.format_status(settings) in output
    assert "Started a new conversation." in output
    assert "First answer" in output and "Fresh answer" in output
    assert len(provider.turns) == 2
    assert provider.turns[1].history == ()
    assert len(services) == 1


def test_telegram_receives_the_same_configured_limit(monkeypatch):
    from pam.telegram import bot

    settings = Settings(_env_file=None, drive_max_context_chars=321)
    monkeypatch.setattr(bot, "create_model_provider", lambda _: object())
    monkeypatch.setattr(bot, "create_mcp_server", lambda _: object())
    monkeypatch.setattr(bot, "local_client_from_server", lambda _: object())
    captured = {}

    def capture_service(*args, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(bot, "ConversationService", capture_service)
    bot.build_conversation_service(settings)
    assert captured["drive_max_context_chars"] == 321
