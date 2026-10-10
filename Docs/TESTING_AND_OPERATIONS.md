# Testing and operations

## Quality gates

Run commands from the repository root using the project environment. On Windows the explicit interpreter form avoids accidentally invoking a different Python installation:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy pam
.\.venv\Scripts\python.exe -m pytest
git diff --check
```

On Linux/macOS use the corresponding `.venv/bin/python -m ...` commands. Use `uv sync --locked --extra dev` to build the dependency set described by the lockfile; if an old virtual environment is incomplete, repair it with the project's environment tool rather than mixing arbitrary global packages.

## Test architecture

Tests live under `pam/tests` and are designed to be offline and deterministic. They use fake Calendar readers, scripted model providers, local MCP adapters, fake Telegram updates, and fake/persistent memory services. This verifies validation, availability calculation and presentation, OAuth state/credential boundaries, provider orchestration, tool restrictions, memory failure policy, and Telegram ownership without consuming remote API quota.

Live acceptance checks are separate operational work. They require protected credentials and should never be recorded by pasting tokens, callbacks, or secrets into test output. A successful HTTP 200 from a storage endpoint alone does not prove a durable memory can be recalled; validate recall in the same owner container with a real subsequent conversation.

## Runbooks

### Calendar returns `calendar is unavailable`

1. Check protected service logs for the layer/category, not credential values.
2. Confirm Google-mode configuration exists for the active process and the credential path is present and readable by that service account.
3. Preserve the credential file. Check Fernet-key continuity and deployment path configuration.
4. If the protected diagnostic shows reconnect required or `invalid_grant`, run the safe reauthorization flow in [GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md).
5. Verify a read-only availability request after reconnection.

### Model-provider outage

Confirm which configured provider is selected and that its protected key/base URL/model settings are present. PAM does not automatically fall back from one provider to another. Check provider status and structured error category; do not log or paste request headers and API keys.

### Memory failure

Recall and passive ingestion failures should not stop normal conversation. Explicit Remember/Forget must return a failure message if the memory backend is unavailable. Check backend enablement, protected key/base URL configuration, outbound network policy, and service diagnostics. Do not inspect other owners' containers as a troubleshooting shortcut.

### Telegram failure

Verify a single PM2 polling process, token configuration presence without printing it, allowed-user configuration syntax, and outbound network access to Telegram. Check PM2 logs and restart the one process only after correcting configuration. Rotate a bot token immediately if it was exposed.

## Operational checks

* `GET /health` confirms the FastAPI process is reachable; it does not prove Google, providers, Telegram, or memory are healthy.
* Use a bounded read-only availability request to test the Calendar path.
* Use an allowlisted Telegram account to test authorization, `/new`, and a normal response.
* Check PM2/systemd after updates and reboots.
* Retain only the minimum operational logs required for support and incident response.

## Logging and privacy

PAM's JSON formatter attaches level, logger, message, and safe extra fields; HTTP middleware adds a request ID. The formatter redacts common secret names such as API key, authorization, credential, password, secret, and token, including assignment-like strings. Redaction reduces risk but is not permission to log sensitive content. Prefer categories, error types, counts, duration, and hashed identifiers over raw messages, Calendar events, memory, or provider payloads.
