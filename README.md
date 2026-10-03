# PAM

PAM is a private, self-hosted personal assistant that answers natural-language
Google Calendar availability questions. It is designed for one authorized user,
is delivered through Telegram in production, and includes a local CLI for
development and manual verification.

PAM combines a conversational model with a deliberately narrow Calendar tool:
it can read availability but cannot create, edit, delete, or otherwise modify
Calendar events.

## What PAM does

- Answers questions such as “How busy am I next Monday?” and “When am I free
  this week?”
- Reads Google Calendar through a validated, read-only Calendar boundary.
- Produces weekly availability summaries with merged overlapping events and
  clear `Free day` results.
- Runs as a private Telegram bot restricted to configured user IDs.
- Provides a local interactive CLI for development and troubleshooting.
- Keeps bounded short-term conversation history per session.
- Optionally stores durable, owner-scoped preferences with Supermemory.
- Supports `Remember that ...`, `Forget that ...`, and `/new`.

`/new` clears recent conversation context only. It does not delete durable
memory, Google credentials, or Calendar data.

## Architecture

```text
Telegram or CLI
       |
       v
ConversationService
       |-- BharatCode model provider
       |-- Supermemory durable memory (optional)
       `-- read-only MCP tool: get_weekly_availability
                    |
                    v
            AvailabilityService
                    |
                    v
             Google Calendar
```

The model never talks to Google Calendar directly. It can request only the
approved `get_weekly_availability` MCP tool; PAM validates its arguments before
the Calendar service runs. The deterministic Calendar domain layer handles date
ranges, time zones, overlapping events, formatting, and safe failures.

PAM also exposes a small FastAPI availability endpoint for local integration and
OAuth support. Production Telegram uses polling, so FastAPI does not need to run
continuously for the deployed workload.

## How the product works

### Calendar conversation

The configured model provider interprets a user question and requests Calendar
data only when needed. BharatCode is the normal production provider through its
OpenAI-compatible chat-completions API; Gemini remains an optional comparison
provider. Offline tests use fakes and scripted providers and make no external
service calls.

The only model-callable Calendar capability is the read-only MCP tool. Unknown
or write-like tool names are rejected. Calendar data is authoritative for the
current request.

### Telegram and CLI

The Telegram adapter authorizes the sender, forwards text to
`ConversationService`, and returns a safe text reply. It does not call Google
Calendar, MCP, or model-provider APIs itself. Supported commands include:

- `/start` — introduces PAM.
- `/help` — displays interaction guidance.
- `/new` — clears the active short-term session.

Telegram uses polling. Only one machine may poll a bot token at a time, so a
local Windows bot must be stopped before the Azure production worker starts.

### Memory

Short-term history is bounded in-memory context controlled by PAM. It is
isolated per session and cleared by `/new` or restart.

Durable memory is optional and uses Supermemory. CLI and Telegram have separate
memory owners; Telegram ownership is derived from the authorized user. Recalled
memory is bounded and is supplied to the model as **untrusted context**, never
as an instruction. A stored prompt-injection attempt cannot expand the tool
allowlist or enable Calendar writes.

Explicit `Remember that ...` requests use durable-memory persistence. Successful
ordinary conversations may be ingested for asynchronous extraction. `Forget
that ...` performs owner-scoped exact-memory removal. Live Calendar data and the
current user message always take precedence over remembered preferences.

## Security and privacy

- Calendar access is read-only: no write scope, write API, or write tool exists.
- Calendar ranges and time zones are validated before data is read.
- Telegram access is limited to the configured numeric user-ID allowlist.
- OAuth credentials, tokens, encryption keys, model API keys, Telegram tokens,
  and credential-store contents are never sent to the model, MCP, replies, or
  normal logs.
- `.env` and `.pam-google-credentials.bin` are Git-ignored and must never be
  committed.
- Memory containers are opaque and owner-scoped, preventing cross-user recall
  and forgetting.

## Local development

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- An ignored `.env` based on [`.env.example`](.env.example)

Create the locked environment with development tools:

```powershell
uv sync --locked --extra dev
```

Run the complete quality suite:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy pam
.\.venv\Scripts\python.exe -m pytest
```

For offline development, keep the fake Calendar backend and fake model provider.
The test suite uses no real credentials or network calls.

### Run the CLI

With a supported provider and Calendar backend configured in the ignored `.env`:

```powershell
.\.venv\Scripts\python.exe -m pam.conversation.cli
```

Ask a Calendar question, use `/new` to reset local session context, or type
`quit` / `exit` to leave.

### Run Telegram locally

With Telegram enabled and the user allowlist configured in `.env`:

```powershell
.\.venv\Scripts\python.exe -m pam.telegram.bot
```

Do not run it while another machine is polling the same bot token.

### Run the local HTTP service

The HTTP service is useful for local OAuth and availability integration testing:

```powershell
.\.venv\Scripts\python.exe -m uvicorn pam.main:app --reload
```

Useful endpoints include `GET /health`, `POST /availability`, and Google OAuth
routes when configured. Entering `/availability` directly in a browser returns
`405 Method Not Allowed` because it intentionally accepts only `POST`.

## Configuration

PAM reads `PAM_`-prefixed settings from the environment and ignored `.env` file.
See [`.env.example`](.env.example) for safe placeholders and the complete list.

Configuration covers:

- application environment and secret;
- Google Calendar OAuth and encrypted credential storage;
- BharatCode or Gemini provider selection;
- bounded conversation history;
- optional Supermemory durable memory; and
- Telegram enablement, token, and allowlist.

Never put real values in source files, documentation, commits, logs, or chat.

## Documentation

- [Production deployment](Docs/PRODUCTION_DEPLOYMENT.md) — Azure VM, PM2,
  releases, rollback, operations, and acceptance checks.
- [Local Google OAuth](Docs/LOCAL_GOOGLE_OAUTH.md) — read-only Calendar setup.
- [Calendar MCP](Docs/LOCAL_MCP.md) — constrained tool boundary.
- [Local conversation](Docs/LOCAL_CONVERSATION.md) — provider and CLI setup.
- [Conversation history](Docs/LOCAL_CONVERSATION_HISTORY.md) — bounded
  short-term context.
- [Supermemory](Docs/LOCAL_SUPERMEMORY.md) — durable memory configuration and
  acceptance checks.
- [Local Telegram](Docs/LOCAL_TELEGRAM.md) — bot setup and authorization.
- [Implementation plan](Docs/PAM_Implementation_Plan_v0_1.md) — staged design
  and implementation history.

## Verification

The project currently has 133 automated tests covering Calendar availability,
HTTP integration, OAuth wiring, the MCP boundary, conversation orchestration,
provider adapters, Telegram, short-term history, durable memory, and
safety/error policies. Run the quality suite above before opening a pull request
or restarting production.
