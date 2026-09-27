# PAM Implementation Plan v0 1

## Goal

Build PAM v1 as a private, self-hosted, single-user, read-only Google Calendar assistant. It returns the requested weekly availability through Telegram, with optional voice-note input and text-only replies.

This plan is deliberately sequential. Do not begin a phase until its completion gate passes. Each phase creates a stable layer used by every later phase.

## Dependency Map

```text
0 Foundation
  -> 1 Domain rules and availability math
    -> 2 Application service with fake Calendar data
      -> 3 FastAPI internal API
        -> 4 Google OAuth and real Calendar read adapter
          -> 5 Calendar MCP tool
            -> 6 Telegram text integration
              -> 7 Natural-language agent harness
                -> 8 Voice-note STT
                  -> 9 Docker Nginx deployment
                    -> 10 End-to-end acceptance and hardening
```

## Non-Negotiable Rules for Every Phase

- Run formatter, linter, type check, and full test suite before moving ahead.
- Add unit tests for new pure logic and integration tests at the boundary introduced in that phase.
- No Calendar write scope, write API, or write tool is permitted.
- No TTS, audio response, WebSocket, or HTTP streaming is permitted in v1.
- Never commit secrets, OAuth tokens, `.env` files, or real Calendar data.
- Every external dependency is injected behind an interface and mocked in tests.
- Every error path returns a safe failure; PAM never invents Calendar data.

## Phase 0 — Repository Foundation

### Build

1. Create the Python 3.12 repository and virtual environment.
2. Add FastAPI, Pydantic, pytest, pytest-asyncio, HTTPX, Ruff, mypy, and Docker tooling.
3. Create the package skeleton:

```text
pam/
  api/
  domain/
  application/
  integrations/
  security/
  tests/
```

4. Add environment configuration models with placeholder values only.
5. Add `/health` endpoint and structured application logging with request IDs.
6. Add CI that runs formatting, linting, type checks, and tests on every push.

### Tests

- Configuration rejects missing required values in production mode.
- `/health` returns a successful response.
- A test confirms logs redact known secret-field names.

### Completion Gate

`pytest`, Ruff, and mypy pass on a clean clone. The app starts locally and `/health` responds.

## Phase 1 — Calendar Domain and Availability Math

### Build

1. Define framework-independent domain models: `CalendarEvent`, `TimedInterval`, `DayAvailability`, and `WeeklyAvailability`.
2. Implement pure functions to:
   - convert event times to `Asia/Kolkata`;
   - split an event across day boundaries;
   - sort and merge overlapping or touching intervals;
   - calculate union duration;
   - distinguish timed events from all-day commitments;
   - mark a day `Free day` only when it has neither type of event.
3. Implement the agreed Telegram-ready formatter.

### Tests

- Empty week produces `0 hours busy — Free day` for every day.
- Simple event produces the correct duration and event line.
- Overlap and nested-overlap cases do not double-count time.
- Adjacent events merge correctly.
- Events crossing midnight split correctly.
- All-day, recurring-instance, daylight-saving source-time, and malformed-event cases are handled deterministically.

### Completion Gate

The availability function is 100% local: no FastAPI, Google, ADK, Telegram, MongoDB, or model dependency. A fixture-driven test produces the exact weekly output format.

## Phase 2 — Application Service with a Fake Calendar

### Build

1. Define a `CalendarReader` interface with one method that reads events for a validated time range.
2. Build `AvailabilityService`, which calls `CalendarReader` and then the Phase 1 calculator.
3. Build an in-memory fake Calendar reader for development and tests.
4. Add date-range validation: only explicit requested ranges, sensible maximum length, and `Asia/Kolkata` display timezone.
5. Create the only v1 application operation:

```text
get_weekly_availability(start_date, end_date, timezone)
```

### Tests

- Service calls the reader once with the exact validated range.
- Invalid or reversed dates fail before reaching the reader.
- Reader failure becomes a clear `CalendarUnavailable` application error.
- The service output matches Phase 1 expected output using fake events.

### Completion Gate

A local script can request a week from the fake reader and print the exact final summary. The core product behavior works with no external account.

## Phase 3 — FastAPI Internal API

### Build

1. Add `POST /availability` for local development only.
2. Validate a request body containing start date, end date, and timezone.
3. Map application errors to stable HTTP errors without leaking stack traces.
4. Add request IDs and redacted structured audit events in memory or test doubles.
5. Keep the endpoint separate from Telegram-specific code.

### Tests

- Valid request returns the agreed weekly response.
- Invalid range returns a validation response.
- Fake Calendar failure returns a safe unavailable response.
- Logs contain a request ID but no event description or secret.

### Completion Gate

FastAPI's test client can exercise the entire local path: HTTP request -> application service -> fake Calendar -> deterministic response.

## Phase 4 — Google OAuth and Read-Only Calendar Adapter

### Build

1. Create the Google Cloud OAuth client configuration for Calendar read-only access only.
2. Implement OAuth start and callback routes locally.
3. Implement encrypted refresh-token storage behind a `CredentialStore` interface.
4. Implement `GoogleCalendarReader`, satisfying the Phase 2 `CalendarReader` interface.
5. Query only the primary calendar and the validated `timeMin`/`timeMax` interval; expand recurring events.
6. Add explicit token-refresh and consent-revoked handling.

### Tests

- OAuth state validation rejects mismatched state.
- Credential-store tests verify only encrypted token bytes are persisted.
- Mocked Google client receives read-only list parameters and no write method is exposed.
- Expired/revoked credentials produce a reconnect-needed error.

### Integration Check

On a local machine, complete OAuth with Ayush's Google account and run one manually chosen week. Verify the output against Google Calendar. Do not expose this local OAuth callback publicly yet.

### Completion Gate

The exact Phase 3 endpoint works with the real Google Calendar while preserving all Phase 1 calculation tests.

## Phase 5 — Calendar MCP Tool Boundary

### Build

1. Expose `get_weekly_availability` through a small read-only Calendar MCP adaptor/server.
2. Use strict Pydantic schemas for tool input and output.
3. Implement an MCP client configuration used by the future agent runtime.
4. Ensure the MCP process/tool can only invoke `AvailabilityService`; it has no Calendar write methods.
5. Add tool metadata describing range limits, read-only policy, and expected errors.

### Tests

- MCP tool schema rejects invalid dates and unknown fields.
- MCP call result equals a direct `AvailabilityService` result.
- Tool discovery exposes exactly one Calendar tool.
- A regression test proves no create/update/delete Calendar API method is reachable.

### Completion Gate

An MCP inspector or test client can call the one tool successfully with fake and real read-only Calendar adapters.

## Phase 6 — Telegram Text Bot

### Build

1. Create the Telegram bot and store its token only in local/server environment configuration.
2. Add `POST /telegram/webhook`.
3. Validate Telegram's webhook secret and enforce Ayush's Telegram user ID allowlist.
4. Implement deterministic commands first:
   - `/week`
   - `/nextweek`
   - `/help`
5. Convert command output to Telegram text messages through a `TelegramClient` interface.
6. Set up the webhook only after local tests pass.

### Tests

- Unknown user receives no Calendar data.
- Missing/wrong webhook secret is rejected.
- `/week` maps to the correct date interval.
- Telegram API send failure is handled safely and logged without content.
- Webhook integration test runs the full path using a fake Telegram client and fake/real-safe Calendar reader.

### Completion Gate

From Telegram, Ayush can run `/week` and receive the exact weekly summary from the real read-only Calendar. No model has been added yet.

## Phase 7 — Natural-Language Agent Harness

### Build

1. Add the BharatCode OpenAI-compatible provider adapter.
2. Configure one Google ADK agent with the MCP Calendar toolset.
3. Add harness policy before every model call: allowlisted user, one tool only, token ceiling, timeout, maximum one retry, and strict date-range validation after tool selection.
4. Route non-command typed messages through the agent.
5. Keep final availability formatting deterministic; the model never receives OAuth credentials or performs calculations.
6. Add safe clarifications for ambiguous requests such as `next Monday` if date interpretation is uncertain.

### Tests

- Model mock can choose only `get_weekly_availability`.
- Attempted arbitrary tool name is rejected by the harness.
- Prompt-injection text cannot change tool policy or request secrets.
- Model timeout/failure falls back to a clear message; `/week` still works.
- Natural-language fixture produces a validated Calendar range and the deterministic expected output.

### Completion Gate

Ayush can type `What does my next week look like?` in Telegram and receive the correct read-only summary. Commands continue to work if the model provider is disabled.

## Phase 8 — Voice-Note Speech to Text

### Build

1. Add Telegram voice-note detection behind the already-authenticated webhook route.
2. Implement `SpeechToText` interface and a Deepgram pre-recorded STT adapter.
3. Enforce maximum voice-note duration and file size.
4. Download to an isolated temporary directory, transcribe once, and delete in `finally` on success or failure.
5. Send the transcript through the exact Phase 7 typed-message path.
6. Return Telegram text only; do not add TTS.

### Tests

- Only the allowlisted user can invoke STT.
- Temporary audio is deleted after successful and failed transcription.
- STT failure asks for a typed message or shorter note.
- Mock transcript routes to the same natural-language/command service used by text.

### Completion Gate

Ayush can send a short Telegram voice note requesting a week and receive the same text response as an equivalent typed request. No audio or transcript is retained.

## Phase 9 — Persistent State and Operational Audit

### Build

1. Replace Phase 3 test doubles with MongoDB repositories for encrypted OAuth credentials, user configuration, rate-limit counters, and redacted audit events.
2. Add retention indexes: audit events expire after 30 days; rate-limit entries expire automatically.
3. Implement startup checks for database connectivity and required secrets.
4. Fail closed if credentials/configuration storage is unavailable.

### Tests

- Repository contract tests run against an isolated MongoDB test container.
- Stored OAuth token is not readable plaintext.
- Audit record contains metadata only, never event content, transcript, or secret.
- Database outage blocks Calendar processing safely.

### Completion Gate

Restarting PAM preserves authorized configuration and token state, while the Calendar itself remains only in Google Calendar.

## Phase 10 — Docker, Nginx, and Production Verification

### Build

1. Create Dockerfiles and Compose configuration for PAM and MongoDB on a private network.
2. Configure Nginx for TLS, HTTP-to-HTTPS redirect, webhook proxying, request size limit, and timeouts.
3. Inject production secrets through server environment configuration, not source files.
4. Set restart policies, health checks, log rotation, backup policy for MongoDB, and certificate renewal.
5. Configure Telegram webhook to the HTTPS production URL.

### Tests

- Compose integration test: PAM can reach MongoDB while the database port is not public.
- Nginx route test: only intended webhook/health routes are reachable.
- Restart test: containers recover and `/health` becomes ready.
- Production smoke test: `/week`, natural language, and one voice note work using real accounts.

### Completion Gate

PAM is deployed on the existing server, HTTPS is valid, only Ayush can access Calendar data, and every v1 acceptance test passes.

## Final Acceptance Checklist

- Each day is shown with busy hours; empty days show `0 hours busy — Free day`.
- Overlapping events are never double-counted.
- Calendar access is read-only and confined to the requested range.
- Unknown Telegram users get no data.
- Typed commands work without the LLM.
- Natural-language text works with one bounded tool.
- Voice notes transcribe to text and create no retained audio or TTS output.
- OAuth tokens, API keys, event details, and transcripts never appear in logs or Git.
- The system works after a container restart and fails safely when an external service is down.
