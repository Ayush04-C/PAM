# Google Drive MCP implementation plan

Status: planning proposal for architecture review; no feature implemented.
Audit date: 2026-10-10. Repository baseline: `77a2ebf`.

Current stage: [Stage 1 integration boundaries](STAGE_01_BOUNDARIES.md).
Drive documentation now lives together in `Docs/Driver`; tests remain in `pam/tests`.

Review companion added 2026-10-16: [proposed workflow and architecture diagrams](GOOGLE_DRIVE_ARCHITECTURE.md).
These user-requested draft views do not finalize open architecture decisions or
authorize implementation. The original audit below remains dated 2026-10-10.

## 1. Scope and non-goals

Add read-only Google Drive capabilities to the existing PAM Telegram assistant
and conversation CLI through an independent private Drive MCP server. Deliver
bounded file search/listing, metadata, contextual file references, and supported
content retrieval and summaries. Preserve deterministic Calendar availability,
Phase 10 presentation, Telegram authorization, and memory ownership.

This document is the D0 planning deliverable. D0 implementation-contract signoff
and D1–D7 execution require subsequent approval. Proposed paths, settings, tools,
types, limits, and behavior below do not exist unless explicitly marked existing.
Planning completion does not mean implementation or production readiness.

Non-goals: Drive writes, uploads, deletes, sharing/permission changes, event
creation, public MCP services, background Drive sync/indexing, automatic document
ingestion into Supermemory, unrelated MCP integrations, a second repository,
per-user Google account onboarding, OCR, arbitrary binary parsing, and a final
architecture diagram. No diagram is included; that is a separate review stage.

## 2. Audit method and current PAM baseline

The audit used Tier 2 graph discovery, exact source snippets, a bidirectional
one-hop trace of `ConversationService._respond_in_session`, direct source reads,
tracked-file inventory, and configuration/document/test inspection. Graph project
`D-Learning-PAM` was indexed without a repository artifact; generation
`2026-10-10T11:05:10Z`, 870 nodes and 3,846 edges. Relevant searches and the trace
were untruncated. Coverage checks included audited source paths and `pam`,
`pam/tests`, `Docs`, and `.github` scopes. There were no recorded parse/skipped
source gaps; coverage nevertheless reported `metadata_changed` freshness, so
current filesystem source was used to verify material findings. Python cache
subtrees were excluded. These are best-effort checks, not proof of completeness.

The ignored `.env`, encrypted credential contents, and installed dependency
internals were not inspected. Test names/contracts were inspected; the suite was
not executed during this documentation-only audit. Production state is described
by the deployment guide, not independently verified against Azure. Google API
details were checked against official documentation linked below.

### Existing layout and responsibilities

| Existing location | Audited responsibility |
| --- | --- |
| [`pam/domain`](../../pam/domain) | Calendar events, interval math, formatting, deterministic availability presentation. Calendar domain, not generic file models. |
| [`pam/application/calendar_reader.py`](../../pam/application/calendar_reader.py), [`availability_service.py`](../../pam/application/availability_service.py) | `CalendarReader.read_events`, availability orchestration, inclusive date validation with a 31-day limit and Asia/Kolkata policy. |
| [`pam/integrations/google_calendar.py`](../../pam/integrations/google_calendar.py), [`google_wiring.py`](../../pam/integrations/google_wiring.py) | Calendar OAuth, token refresh, paginated primary-calendar reads, event mapping, Google-mode wiring. |
| [`pam/security/credentials.py`](../../pam/security/credentials.py) | `CredentialStore.save/load` and Fernet-encrypted single refresh-token file. |
| [`pam/api/google_oauth.py`](../../pam/api/google_oauth.py), [`pam/main.py`](../../pam/main.py) | Local OAuth routes, one-time state and PKCE, FastAPI factory, availability HTTP API and health. |
| [`pam/mcp/calendar.py`](../../pam/mcp/calendar.py), [`server.py`](../../pam/mcp/server.py), [`config.py`](../../pam/mcp/config.py) | One Calendar MCP tool, strict schema, stdio entry point, typed launch descriptor. |
| [`pam/conversation`](../../pam/conversation) | Provider-neutral values, Calendar MCP client, bounded orchestration/history, BharatCode/Gemini providers, CLI. |
| [`pam/memory`](../../pam/memory) | Optional durable-memory interface and Supermemory implementation. |
| [`pam/telegram`](../../pam/telegram) | Authorized private-text adapter and outbound polling worker. |
| [`pam/config.py`](../../pam/config.py), [`pam/logging.py`](../../pam/logging.py) | `PAM_` settings, conditional requirements, safe structured logging utilities. |
| [`pam/tests`](../../pam/tests), [`examples`](../../examples) | Offline test suite and fake Calendar example; examples are excluded from graph indexing and are not structural evidence for this plan. |
| [`Docs`](../README.md), [`Architecture`](../../Architecture) | Operational guides and earlier design documentation. |
| [`pyproject.toml`](../../pyproject.toml), [`uv.lock`](../../uv.lock), [CI](../../.github/workflows/ci.yml) | Python >=3.12, setuptools `pam*` discovery, locked dependencies; CI format/lint/type/test gates. |

### Calendar MCP contract and actual client wiring

Existing command: `python -m pam.mcp.server`. Server name: `PAM Calendar`.
Only tool: `get_weekly_availability`. Required inputs are ISO `start_date`,
`end_date`, and IANA `timezone`; optional inputs are
`minimum_duration_minutes` (1–1440) and `requested_time` (validated time;
single-day request only). Extra arguments are forbidden. Application policy
enforces the date range and Asia/Kolkata. Structured output contains exactly the
client-consumed `availability` string and `presentation` object. The server marks
the tool read-only, non-destructive, and idempotent. Errors hide invalid values,
Calendar internals, and reconnection details behind safe messages.

`CalendarMcpClient` is a Calendar-specific protocol, with `discover_tools()` and
`get_weekly_availability(arguments)`. `LocalCalendarMcpClient` opens a new
`mcp.Client(self._server)` context for discovery and each call, filters discovery
to one exact tool, and validates the Calendar result fields. It has no multi-server
registry, generic dispatch method, or application-level timeout setting.

Important source/documentation discrepancy: the CLI's `run` and Telegram's
`build_conversation_service` currently pass
`local_client_from_server(create_mcp_server(settings))`, an injected `MCPServer`
object, rather than the stdio launch descriptor. The SDK owns that object's
transport behavior. The standalone stdio entry point and launch descriptor exist
and have a subprocess test, but the audit does not establish that normal CLI/bot
wiring launches a child process. The current [MCP guide](../MCP_INTEGRATION.md)
describes stdio startup more broadly than this wiring supports. D4 must explicitly
choose/test transport and D4 documentation must correct this distinction.

### Conversation and provider behavior

`ConversationService` holds `calendar_mcp`, permits only
`get_weekly_availability`, and defaults to two tool rounds. Discovery failure
removes all tools; an invocation failure ends the turn with a Calendar error.
It recalls owner-scoped memory, builds a model turn with current time/history,
and commits successful user/assistant messages to `ConversationStore`.

`ToolDefinition`, `ToolCall`, `ToolResult`, and `ModelTurn` in
[`models.py`](../../pam/conversation/models.py) are largely provider-neutral;
`ToolDefinition` has no server identity. `ModelDecision` represents one text
answer or one tool request. BharatCode sends OpenAI-compatible function schemas
with `tool_choice="auto"`, parses only the first returned tool call, requires its
call ID, and sends structured JSON in a tool-role response. It uses a 30-second
SDK timeout and one retry. This timeout is not an MCP/API deadline.

Both BharatCode and Gemini `respond_after_tool` reconstruct initial context plus
only the latest call/result. Previous results in the same turn are not accumulated.
A search → metadata → content → Calendar sequence therefore requires a contract
change and a bounded larger budget, not simply adding Drive tool declarations.
Provider selection in `create_model_provider` is shared and explicit; no automatic
provider fallback exists. Keep Gemini and `ScriptedModelProvider` compatible with
any provider-neutral contract changes.

### OAuth, credentials, authorization, and memory

The exact current scope is
`https://www.googleapis.com/auth/calendar.events.readonly`.
`GoogleOAuthConfig` contains client ID, secret, and redirect URI, but lives in the
Calendar integration. `GoogleOAuthClient._flow` hardcodes Calendar scopes;
authorization requests offline access, consent, and incremental granted scopes.
`exchange_code` returns only a refresh-token string and rejects missing refresh
tokens. Granted scopes/account identity are not persisted.

`GoogleCalendarReader._credentials` loads that string and constructs/refreshes
credentials on every read, with Calendar scopes. It is not a generic credential
manager or cached-token service. Refresh/decryption/missing-token failures require
reconnection; `AvailabilityService` normalizes reader failures to
`CalendarUnavailable`. Calendar listing follows pages until exhausted.

`EncryptedFileCredentialStore` is reusable token encryption/storage code. It has
one configured path (default `.pam-google-credentials.bin`), directly writes the
encrypted token, and attempts mode 600 while suppressing chmod errors. It has no
account namespace, scope metadata, atomic replacement, or write lock. The
`google_wiring` helper uses the one Calendar settings path. Settings validate
Google configuration when `calendar_backend == "google"`, not for Drive.

OAuth HTTP routes are `/oauth/google/start` and `/oauth/google/callback`, enabled
for Google Calendar by `create_app`. State is one-use and process-local, but the
implementation has no TTL or capacity bound. These are local provisioning routes,
not Telegram account authorization or an authenticated public onboarding flow.

Telegram authorization checks allowed numeric user IDs and private chats before
calling conversation logic. Sessions and memory owners are `telegram:{user_id}`;
CLI uses session `cli:local` and its configured memory owner. This isolates memory
and history, but Google access currently uses one operator-configured account.
It does not provide a Google account per Telegram user. Drive must retain this
explicit trust model; allowing a Telegram user means granting them the configured
Drive account's accessible data. Limit the Drive audience to the account owner
initially, with a server-side access policy for any later shared audience.

Memory hazard: a tool-completed answer is committed to short-term history with
`ingest=False`, but a later no-tool answer calls `ingest_turn` with the entire
loaded history. That history can contain earlier tool-derived text. A model text
answer at the start of a subsequent tool-loop iteration also takes the ingest
path. The current test `test_calendar_tool_results_are_not_ingested_as_durable_memory`
covers the immediate Calendar tool turn; it does not establish safe later-history
handling for Drive. Raw tool payloads are not stored in history today, but answers
can quote documents. D5 must close this path before D6 content is enabled.

`InMemoryConversationStore` bounds message/session counts (defaults 20/100), not
message bytes or tool-result bytes. The service's session locks and memory
conversation IDs are separate dictionaries. New file references must not become
another unbounded cache or assume history LRU evicts all service state.

### Existing tests, documentation, and startup

Audited test files include [Google Calendar](../../pam/tests/test_google_calendar.py)
(exact scope, encryption, state, pagination, refresh/revocation),
[Calendar MCP](../../pam/tests/test_mcp_calendar.py) (schemas, no writes, errors,
injected SDK client, stdio subprocess, deterministic presentation),
[conversation](../../pam/tests/test_conversation.py) (allowlist, tool loops,
untrusted results, offline MCP), [history](../../pam/tests/test_conversation_history.py)
(bounded isolation, follow-ups, `/new`), [BharatCode](../../pam/tests/test_bharatcode.py)
(call IDs, schemas, history, failure mapping), [memory](../../pam/tests/test_memory.py)
(owner scope, ingestion, explicit actions, tool-turn exclusion), and
[Telegram](../../pam/tests/test_telegram.py) (private authorization, chunking,
ownership, offline integration). [Config](../../pam/tests/test_config.py),
[prompt](../../pam/tests/test_system_prompt.py), and
[domain](../../pam/tests/test_domain_availability.py) tests are regression gates.

Existing entry points: `python -m pam.conversation.cli`,
`python -m pam.telegram.bot`, `python -m pam.mcp.server`, and the FastAPI
`pam.main:app` factory/application. The bot builds dependencies once and runs
long polling. [Production deployment](../PRODUCTION_DEPLOYMENT.md) records Azure
Ubuntu 24.04, Python 3.12/uv, one PM2 `pam-telegram` worker restored by systemd,
and 1 GiB swap. No permanent FastAPI/Nginx/public listener is required for polling.
The tracked inventory contains CI but no checked-in PM2 ecosystem file; startup
commands are in the guide. Existing Google/MCP/provider/memory SDKs suffice for
the proposed Google Docs/plain-text first release; no new dependency is planned.

## 3. Design principles and architecture decisions

1. Keep one repository and one installed `pam` distribution. The audit shows
   shared config, providers, Telegram transport, credential encryption, tests,
   and deployment; no independent release/team boundary justifies another repo.
2. Preserve `pam.mcp.server`, the Calendar tool name/schema, and Calendar domain
   semantics. Add `pam.drive` with its own MCP server and no imports from
   `pam.domain`, `pam.application` Calendar services, or `pam.mcp.calendar`.
3. Reuse genuinely generic values/storage/logging/providers. Extract narrowly
   scoped Google OAuth plumbing with explicit scopes; do not reuse Calendar
   reader, availability types, or Calendar-specific MCP protocol for Drive.
4. Make Drive optional and disabled by default. Invalid/missing Drive grants or
   runtime failures must not prevent Calendar-only startup or operation.
5. Use read-only API operations and independent allowlists in Drive server and
   conversation router. MCP annotations alone do not enforce permissions.
6. Minimize Google scopes and model context. Do not add write scopes to make reads
   easier. Resolve consent policy before exposing content to a hosted model.
7. Apply Telegram authorization before discovery/reads and preserve owner/session
   isolation. File IDs are references, not authorization tokens.
8. Treat file names, metadata, content, tool errors, and model decisions as
   untrusted. Separate retrieved data from system instructions structurally.
9. Never automatically persist Drive documents, excerpts, or derived answers in
   Supermemory, including via later history or recall queries.
10. Bound API pages, content bytes/chars, tool rounds, concurrency, deadlines,
    retries, history, and references. Avoid resident indexers or extra PM2 workers.

## 4. Proposed repository structure and ownership

All paths in this block are proposed additions except the noted existing files.
Create only what each stage needs; keep this layout small.

```text
pam/
  drive/
    __init__.py
    models.py          # Drive values, page/content contracts, safe errors
    reader.py          # DriveReader protocol and fake implementation
    service.py         # validation, bounds, permitted retrieval policy
    google_drive.py    # Drive v3 mapping and API calls only
    wiring.py          # Drive-specific settings/credentials construction
    mcp/
      __init__.py
      tools.py         # strict schemas and Drive tool allowlist
      server.py        # independent python -m pam.drive.mcp.server
  integrations/
    google_oauth.py    # extracted scope-aware Google config/OAuth/refresh helpers
    google_calendar.py # existing Calendar API adapter; compatibility maintained
    google_wiring.py   # existing Calendar wiring
  conversation/
    tool_router.py     # fixed Calendar + Drive registry and dispatch policy
    file_context.py    # bounded owner/session file-reference store
    mcp_client.py      # existing Calendar client; narrowly reuse transport helpers
    models.py          # existing portable models, bounded exchange/provenance additions
  security/credentials.py # existing encrypted-token store reused
  tests/
    test_drive.py
    test_drive_oauth.py
    test_mcp_drive.py
    test_tool_router.py
    test_drive_conversation.py
    test_drive_content.py
```

Keep the legacy Calendar modules/entry point rather than undertaking a broad
package move. Shared launch configuration can remain in `pam/mcp/config.py`;
its descriptor is generic but `local_stdio_launch_config` is Calendar-specific.
Add an explicit Drive launch factory, not a model-controlled module argument.
If transport extraction is necessary, limit it to fixed launch/session mechanics.
Do not introduce a plugin platform for future unrelated servers.

| Owner boundary | Responsibility and dependency direction |
| --- | --- |
| Calendar domain/application/MCP | Availability only. No Drive imports or Drive errors in Calendar responses. |
| Drive domain/application/API | File operations and safe retrieval. Imports shared credential/OAuth infrastructure, never Calendar types. |
| Drive MCP | Own schemas/entry point/allowlist, delegates only to injected Drive service; no model or Telegram implementation. |
| Shared Google infrastructure | Explicit client config, scopes, PKCE/exchange/refresh mechanics; no Calendar/Drive business decisions. |
| Conversation router/service | Authorized capability exposure, fixed dispatch, budgets, partial failures, transient exchanges, memory policy. |
| Provider adapters | Serialize portable schemas/exchanges and parse decisions; no Google credentials or arbitrary execution. |
| Telegram/CLI | Identity, input/reply transport, `/new`, composition root. No direct Drive API calls. |
| Memory | Explicit owner-scoped preferences/facts and sanitized passive context; never an automatic Drive repository. |

## 5. Existing code reuse matrix

| Exact existing component | Reuse decision | Necessary change / prohibited reuse |
| --- | --- | --- |
| `CredentialStore`, `EncryptedFileCredentialStore` in `pam/security/credentials.py` | Reuse at a separate Drive path with the existing encryption-key infrastructure. | Require distinct paths; safe atomic replacement/permissions behavior may be added in D1 with Calendar regression tests. Token strings alone do not track grants. |
| `GoogleOAuthConfig`, `GoogleOAuthClient` in `pam/integrations/google_calendar.py` | Extract scope-independent plumbing to proposed `google_oauth.py`; keep Calendar imports/behavior compatible. | Parameterize scope sets explicitly; return exchange grant metadata; no Drive imports of Calendar module. |
| `GoogleCalendarReader._credentials` | Reuse Google SDK refresh approach after extracting a small helper. | Not reusable as-is: hardcoded scopes, Calendar errors, per-read refresh. Preserve Calendar refresh behavior initially. |
| `google_oauth_config`, `credential_store` in `google_wiring.py` | Keep Calendar factories intact; reuse patterns. | Add Drive wiring; do not point both factories at one file or enable Drive based on `calendar_backend`. |
| `OAuthStateStore`, `InMemoryOAuthStateStore`, `create_google_oauth_router` | Reuse PKCE/one-time-state approach and local provisioning surface. | Add provider/capability-bound state with expiry/capacity and distinct Drive routes; existing router type/imports are Calendar-bound. |
| `McpServerLaunchConfig` in `pam/mcp/config.py` | Reuse fixed stdio descriptor. | Calendar launch helper stays compatible; add Drive factory and resource limits in client wiring. |
| `LocalCalendarMcpClient`, `CalendarMcpClient` | Retain Calendar adapter/validation; reuse only vetted transport lifecycle mechanics. | No current multi-server support; add explicit Drive adapter and router. Do not route Drive output through availability validation. |
| `ToolDefinition`, `ToolCall`, `ToolResult`, `ModelTurn` | Reuse portable models. | Add internal server/route identity, accumulated exchanges and provenance/bounds without trusting model-supplied identity. |
| `ModelProvider`, `BharatCodeProvider`, `GeminiProvider`, `ScriptedModelProvider` | Reuse provider selection/schema conversion and fake harness. | Extend bounded transcript serialization; handle multiple returned calls deliberately rather than silently executing the first. |
| `ConversationService` | Reuse session coordination and model loop. | Replace one-tool branch with registry; independent discovery/errors, combined answers, content-safe memory policy. |
| `ConversationStore`, `InMemoryConversationStore` | Reuse bounded session/history behavior. | Add byte/provenance policy or conservative session ingestion suppression; coordinate file-reference eviction and `/new`. |
| `MemoryService`, `SupermemoryMemoryService` | Keep owner-isolated recall and explicit memory actions. | Filter unsafe history/query inputs in the orchestrator; do not call document ingestion for Drive. |
| `TelegramAdapter`, `ConversationResponder`, `split_telegram_text` | Reuse authorization, owner derivation, plain-text chunking. | Update help/capability text only after enablement; content policy remains upstream. |
| `create_model_provider`, CLI `run`, Telegram `build_conversation_service` | Reuse provider factory and transport composition. | Add a shared conversation construction function used by both; current factory creates providers only. |
| `Settings`, `configure_logging`, `JsonFormatter` | Reuse typed settings and safe logging framework. | Add independent Drive settings validation and minimal telemetry; redaction does not make file content safe to log. |
| Calendar domain, `CalendarReader`, `AvailabilityService`, presentation builder | Preserve as regression authority. | No reuse for Drive file types, validation, pagination, or summaries. |
| Existing Google/MCP/Pydantic SDK dependencies and CI | Reuse installed/locked foundation. | Verify locked SDK semantics in D3/D4; no version upgrade or parser dependencies by default. |

## 6. Shared integration contracts (proposed)

### Tools and result shapes

Keep public Calendar name `get_weekly_availability`. Drive names have the
`drive_` prefix in both its server and provider exposure. Maintain an immutable
mapping from public name to `(server_id, remote_name, input validator, result
validator, access policy)`. Server IDs are fixed `calendar` and `drive`.
Reject collisions and unexpected/changed schemas before exposure; never guess a
server from an argument, description, prefix alone, or discovery order.

| Proposed tool | Inputs | Structured success result |
| --- | --- | --- |
| `drive_search_files` | Bounded `query_text`, optional approved MIME filter, `page_size` 1–50 (default 20), optional opaque cursor. | `files: FileMetadata[]`, `next_cursor`, `incomplete_search`, `scope_description`. |
| `drive_list_files` | Optional `folder_id`, `page_size`, cursor; fixed non-trashed user corpus. | Same `FilePage` contract; folders have metadata, not content. |
| `drive_get_file_metadata` | Bounded opaque `file_id`; optional resource key only through validated reference context. | `FileMetadata`: ID, name, MIME type, modified time, optional size, validated web URL, retrieval capability; optional shortcut target metadata. |
| `drive_get_file_content` (D6 only) | Validated `file_id`/approved reference; optional bounded passage selector if approved. No arbitrary URL, export MIME, local path, or requested byte-limit override. | `FileContent`: source ID/name/MIME/modified time, export MIME, bounded text passages and labels, byte/character counts, truncation status, source citation, `untrusted=true`. |

Every input schema forbids extras, validates types/lengths and excludes raw
Drive `q`, OAuth, shell, upload, permission, and generic fetch arguments. Query
construction uses fixed operators and escaped literals. `FileMetadata` may lack
size for Workspace files; never interpret absent size as zero. Names are display
data, not unique identifiers. Metadata selection avoids owners, email addresses,
permissions, and thumbnails unless needed for an explicitly reviewed contract.

Opaque pagination cursor is bound to owner/session, filters, folder, corpus,
expiry, and account/grant context by the host-side context layer; the Drive API
page token itself is not authority. Return `incomplete_search` honestly and allow
empty pages with a next token. No automatic exhaustive scan. D2 owns API page
handling; D5 owns conversational cursor/reference binding.

### Errors, timeouts, and budgets

Proposed typed error envelope: `server_id`, approved `code`, safe `message`,
`retryable`, and optional bounded `retry_after_seconds`; no raw exception, URL
query, response body, document title, or token. Drive codes:
`invalid_input`, `not_connected`, `reconnect_required`, `insufficient_scope`,
`not_found_or_denied`, `rate_limited`, `unsupported_type`, `content_too_large`,
`invalid_cursor`, `timeout`, `unavailable`. Preserve Calendar's existing external
contract; adapt its failures internally rather than changing Calendar output.

Starting bounds for review: at most 50 files/page, one page/tool invocation,
three explicitly requested pages/turn, 512-character search text, 256-character
file IDs, six sequential tool invocations for Drive/combined turns, and the
existing two-round Calendar-only budget. Maximum 1 MiB transferred bytes per
content read, 20,000 extracted characters per file, and 40,000 total content
characters/turn; stop stream transfer at the byte cap even when size is unknown.
Add a separate provider-token budget before serialization; never assume character
counts guarantee token fit. Keep only bounded transient passages for the turn.

Proposed Drive HTTP timeout 10 seconds, discovery 5 seconds, call deadline
20 seconds, and overall tool-work deadline 60 seconds (model calls separately
bounded by provider settings). At most two retry attempts for transient reads,
with jitter and a capped retry-after within remaining deadlines; no retries for
validation/permission/unsupported errors. Acquire no more than two concurrent
Drive operations process-wide and one content read per session. SDK retries must
not multiply application retries. These are future targets, not current promises;
D4/D7 must measure and adjust on the actual VM. Cancellation must stop/contain
underlying I/O, not merely stop awaiting an unbounded thread.

### Google account and grant contract

Use existing operator-provisioned single-account mode initially. Reuse encryption
code/key management, not the Calendar token file. Proposed Drive token path:
`.pam-drive-credentials.bin`, separately ignored and protected during D1 execution.
Granted scopes, configured client identity and a non-secret account/grant binding
need a small protected versioned metadata record or credential envelope. Do not
silently reinterpret the legacy Calendar encrypted string as a new envelope.
Approve that format in D1; legacy Calendar reads must remain compatible.

Separate files provide storage isolation only. Shared Google client/project and
incremental authorization can aggregate grants, and revocation can affect both
capabilities. The recommended first implementation uses a dedicated Drive OAuth
client and token store while reusing OAuth code; review whether the consent/project
boundary also needs separation for the required revocation guarantee. A separate
repository is unnecessary. Validate actual granted scopes and live acceptance;
assigning `scopes` to a credentials object does not grant new access.

## 7. Ordered development stages

Dependency order: D0 signoff → D1 → D2 → D3 → D4 → D5 → D6 → D7.
D2 fake models can be developed before live consent, but live API acceptance
depends on D1. No content tool is exposed before the D5 memory/security gate.
For every stage, definition of done includes reviewed contracts, appropriate
offline tests passing, Calendar regression gates passing, and updated docs.
Tests listed here are planned work, not tests added/run by this planning task.

### D0 — Repository audit and integration contract

**Objective:** approve evidence-based package boundaries, reuse, and data/security
contracts before feature implementation.

**Prerequisites:** this audit and the current baseline; architecture review of
the decisions in section 11.

**Existing reuse:** exact components and limitations in sections 2 and 5;
existing documentation and CI/test contracts.

**New components:** this implementation plan; subsequent signed contract record.
**Existing modifications:** only this document and the minimal Docs index link
in the planning task. No runtime/test/config changes.

**Responsibilities/data contracts:** architecture owner resolves repository,
credential, transport, audience, and scope decisions; Calendar contract remains
the compatibility anchor. Proposed schemas in section 6 need review, not implicit
approval through this document.

**Tasks in order:**

1. Record actual source baseline, graph/source limitations and documentation drift.
2. Approve independent Drive package/entry point and exact reuse matrix.
3. Select OAuth scope/grant policy and model data-transfer policy.
4. Approve tool/result/error bounds, transcript and memory policy.
5. Record D1–D7 gate owners, decisions, unresolved acceptance evidence, and signoff.

**Unit tests:** inventory current Calendar/domain/config/provider/history tests;
no tests created in D0. **Integration tests:** inventory offline MCP stdio/injected
and Telegram paths; define future live fixtures without contacting production.

**Errors:** disclose source/guide discrepancies and unverified operational facts.
**Security:** inspect no secrets; no OAuth/Google/model calls with user data.
**Acceptance:** all requested audit areas and each D-stage checklist present,
links valid, clean whitespace, documentation-only diff.
**Definition of done:** plan complete and reviewable; implementation-contract D0
gate closes only after review decisions are recorded.
**Documentation:** this file and `Docs/README.md`; architecture diagram deferred.

### D1 — Google Drive configuration and OAuth

**Objective:** provision Drive reads independently without changing existing
Calendar consent/token behavior.

**Prerequisites:** D0 scope, audience, grant separation, and model-transfer policy
approved; Drive API enabled in the selected project during future acceptance.

**Existing reuse:** `Settings`, encrypted credential store, Google SDKs,
`GoogleOAuthConfig`/flow mechanics, PKCE and one-time-state pattern.
**New components:** proposed `pam/integrations/google_oauth.py`, Drive wiring,
Drive-specific grant metadata and local OAuth route/factory.
**Existing modifications:** `pam/config.py`, `pam/api/google_oauth.py`,
`pam/main.py`, narrowly the Calendar OAuth imports/wiring; optional store atomic
write hardening in `pam/security/credentials.py`. Preserve legacy token format.
Future `.env.example`/ignore changes belong to this stage, not this task.

**Responsibilities/data contracts:** OAuth helper accepts explicit client/scopes
and returns token plus granted-scope metadata privately. State binds capability,
client, operator/account expectation, verifier and expiry. The Drive factory owns
its distinct credential path; Calendar keeps its scope/path and errors.

**Tasks in order:**

1. Add proposed `PAM_DRIVE_ENABLED` (false), Drive OAuth client/secret/redirect
   names and credential path; fail validation only for explicitly enabled Drive.
   Reject a resolved Drive path equal to Calendar's path. Decide whether optional
   startup diagnostics disable Drive safely or reject just Drive construction.
2. Extract config/flow/refresh mechanics with explicit scopes and Calendar
   compatibility imports. Preserve exact Calendar requested scope and routes.
3. Add proposed local `/oauth/google/drive/start` and `/callback` routes under
   that prefix. Never expose them as MCP tools or public Telegram onboarding.
4. Bind/expire/cap state and consume once; handle denial, missing code, bad state,
   partial grants, client mismatch and missing refresh token safely.
5. Validate required granted scopes; retain an existing valid Drive token if a
   repeat exchange lacks a replacement. Do not overwrite any token on a failed
   exchange or partial grant. Persist successful replacements atomically.
6. Verify refresh using explicit Drive scopes; keep Drive reconnect/error state
   independent. Safely stage and verify consent/token changes before promotion.
7. Prove Calendar still refreshes/reads after success, denied Drive consent,
   insufficient scopes, Drive reconnect and any planned revocation experiment.

**Unit tests:** exact scope sets; disabled/default config; Drive-enabled with fake
Calendar; distinct paths; wrong key; expiry/replay/cross-capability state;
missing/partial grant; absent refresh token; legacy store compatibility;
atomic-write failure leaves previous credentials usable.
**Integration tests:** fake OAuth router/token refresh and Calendar reader together;
manual non-production consent acceptance with protected credentials, plus
Calendar before/after. Google grant aggregation/revocation behavior must be
tested live rather than inferred from file separation.

**Errors:** distinguish missing grant, insufficient scope, reconnect and transient
network failure; no infinite refresh loop. **Security:** minimum scopes, no token
logging, local-only provisioning, secret settings, permissions checked, protected
backup, no widened existing Calendar grant. Test state TTL/capacity.
**Acceptance:** Calendar credential file remains untouched by Drive provisioning;
Drive-disabled startup has no Drive requirements or calls; live granted scopes
match approved policy. **Definition of done:** OAuth review evidence recorded,
safe reauthorization/rollback documented, all credential/scope regression gates pass.
**Documentation:** update Google OAuth/Calendar local guide for shared extraction,
add Drive setup instructions and configuration reference by names only.

### D2 — Drive domain and API adapter

**Objective:** bounded read-only metadata/search/listing independent of Calendar.
**Prerequisites:** D1 contracts; fake fixtures can precede a live grant.
**Existing reuse:** Google discovery/auth SDKs, extracted OAuth/refresh helper,
`CredentialStore`, Pydantic/dataclass patterns and logging framework.
**New components:** `pam/drive/models.py`, `reader.py`, `service.py`,
`google_drive.py`, `wiring.py`, and `pam/tests/test_drive.py`.
**Existing modifications:** no Calendar domain/adapter changes; only settings
limit additions if D1 did not yet define them.

**Responsibilities/data contracts:** `DriveReader` exposes search/list/get metadata;
fake reader implements the same contract. Adapter translates Drive v3 responses
to `FileMetadata`/`FilePage` and typed errors; service validates policy and limits.
Content capability metadata exists but no content retrieval is exposed yet.

**Tasks in order:**

1. Define strict models, optional fields, safe errors, supported corpus and fake reader.
2. Construct fixed escaped queries (`trashed=false` plus validated name/folder/MIME
   filters); select minimal response fields including next page/incomplete-search.
3. Implement `files.list` and metadata `files.get` with fixed user/Drive space,
   bounded page sizes, deliberate ordering and no automatic whole-Drive scan.
4. Preserve next-page tokens across empty pages; reject invalid/expired cursors
   safely; report incomplete search instead of claiming exhaustive results.
5. Define folders and shortcuts: folders metadata-only; shortcuts display-only
   initially, with no automatic target traversal or external URL fetch.
6. Map 401/refresh errors, denied/not-found reads, scope errors, rate-limit reasons,
   5xx and transport timeouts to approved categories; add bounded retry policy.
7. Make API/client construction injectable; prove no write endpoint is reachable
   through the public adapter interface and no Calendar imports exist.

**Unit tests:** query escaping, missing/invalid fields, duplicate names, Unicode,
deleted/trashed files, absent size, MIME mapping, folders/shortcuts, empty page with
next token, field masks, cursor mismatch, retry exhaustion and no-write surface.
**Integration tests:** fake Drive discovery/service responses exercise actual
adapter + service + encryption/refresh seams; later read-only test-account
search/list/metadata and pagination. Shared drives are explicitly excluded from
the first contract until corpus flags and access acceptance are approved.

**Errors:** ambiguous names return candidates; not-found/denied share a safe
message to avoid leaking existence; rate-limit reasons determine retryability.
**Security:** do not accept raw query expressions or log names/queries; API scopes
are insufficient as app audience enforcement; service access policy still applies.
**Acceptance:** deterministic bounded pages and minimal metadata, no content/write
operations, Calendar unaffected. **Definition of done:** fake/live response shapes
agree, adapter is independently testable, unsupported types are labeled safely.
**Documentation:** Drive metadata/file-type/pagination contract and safe-error table.

### D3 — Independent Drive MCP server

**Objective:** expose only approved Drive reads through a distinct entry point.
**Prerequisites:** D2 contracts and fake reader; D1 for Google-mode acceptance.
**Existing reuse:** installed `MCPServer`, `Tool.from_function`, annotations,
strict Pydantic argument pattern, generic launch descriptor, Calendar MCP test
techniques. Calendar schemas/adapters themselves are not reused.
**New components:** `pam/drive/mcp/tools.py`, `server.py`, package initializers,
`pam/tests/test_mcp_drive.py`.
**Existing modifications:** add explicit Drive launch descriptor factory in
`pam/mcp/config.py`; retain existing Calendar factory output.

**Responsibilities/data contracts:** server name proposed `PAM Drive`; stdio
command `python -m pam.drive.mcp.server`; only search/list/metadata tools from
section 6. Own strict request/result models and safe error mapping.

**Tasks in order:**

1. Build server with injected Drive service and fake/live wiring.
2. Define independent `drive_` schemas, extra-field rejection, value caps and
   read-only/non-destructive/idempotent annotations; lock discovery to allowlist.
3. Translate approved domain errors to structured safe MCP results without
   leaking rejected values or raw API exceptions.
4. Verify stdin/stdout protocol cleanliness, stderr logging, fixed launch path,
   shutdown and cancellation with the actual locked SDK.
5. Test Calendar and Drive discovery independently; content tool stays absent
   until D6. Never register auth/write/network/shell tools.

**Unit tests:** schema snapshots, strict types/lengths, annotations, argument/result
validation, secret-bearing invalid input, no writes/auth/content tools.
**Integration tests:** real SDK client against injected fake Drive server and
actual stdio subprocess; independent Calendar server discovery/output unchanged.
**Errors:** malformed results/protocol failures fail only Drive; no raw internal
tracebacks sent as tool data. **Security:** fixed trusted code entry point and
service injection; annotations reinforced by schema/API/dispatch allowlists.
**Acceptance:** independent server starts and returns approved metadata tools
without constructing Calendar availability services. **Definition of done:** both
transport tests pass, schemas documented and versioned for D4 validation.
**Documentation:** Drive MCP tool guide, startup commands and separation contract.

### D4 — Multi-MCP client and routing

**Objective:** route approved Calendar/Drive tools independently and preserve
multiple results through a bounded turn.
**Prerequisites:** D3 independently tested servers and approved transport policy.
**Existing reuse:** Calendar client/validation, portable models, provider adapters,
launch descriptor and `ConversationService` orchestration seams.
**New components:** `pam/conversation/tool_router.py`, explicit Drive MCP adapter
(kept with Drive client code or router after review), `test_tool_router.py`.
**Existing modifications:** `mcp_client.py`, `service.py`, `models.py`,
`provider.py`, `bharatcode.py`, `gemini.py`, shared factory, and launch config.

**Responsibilities/data contracts:** host-owned registry joins independently
discovered allowlisted schemas. Internal invocation binds server, validator and
access policy to the selected public tool. Accumulated `ToolExchange` records hold
call ID, name, validated result/error and provenance for this turn only.

**Tasks in order:**

1. Keep Calendar-only adapter path working; introduce fixed Calendar/Drive registry
   with duplicate detection, expected schema checks, server identity and result validation.
2. Discover each enabled server independently. One discovery timeout/failure must
   leave healthy tools available; never fail both through one broad exception.
3. Choose lifecycle explicitly: recommended Drive stdio sessions opened on demand,
   serialized/bounded, closed after calls; preserve current Calendar wiring first.
   Injected fake server mode remains for tests. Separate transport helpers from
   Calendar tool/result policy; do not assume descriptor use in the bot today.
4. Supply each child a minimal server-specific environment; Calendar and Drive
   subprocesses must not receive Telegram, BharatCode or Supermemory secrets.
   Because `Settings` reads `.env`, address child cwd/env-file loading explicitly:
   launch from a controlled directory with explicit relevant settings or add a
   narrow server settings loader. Passing a filtered env alone is insufficient.
5. Add deadlines, bounded I/O/concurrency/retries, safe cancellation, shutdown and
   child reaping; do not make slow synchronous API calls block Telegram's loop.
6. Extend provider-neutral turn/exchange contract; serialize all completed calls
   and results in order, keeping BharatCode call IDs paired and Gemini function
   responses structural. Validate selected provider naming/schema requirements.
7. Retain single sequential invocation semantics; disable parallel tool requests
   where supported and reject/normalize multiple requests explicitly with tests,
   rather than silently dropping extra requested calls.
8. Enforce approved budgets; reject unknown/write/colliding/unavailable tools
   before I/O. Remove failed-server tools for the remainder of the turn.
9. Return a safe server-specific error exchange to the model so it can finish
   healthy work; preserve Calendar-only failure wording and deterministic facts.

**Unit tests:** fixed dispatch, collisions, malicious discovery/schema change,
unknown tools, result validation, deadline/retry budget, multi-call handling,
sequential transcript retention/call IDs, Calendar-only behavior.
**Integration tests:** two real fake-backed SDK servers; one unavailable at
discovery, one failing mid-turn, cancellation/child exit, injected vs stdio mode,
four-plus-call combined sequence, no orphan processes or leaked environments.
**Errors:** independent failure categories and explicit partial results; no silent
empty answer or routing retry through the wrong server. **Security:** authority
resides in registry, not model/server descriptions; secrets/content absent from
debug logs; cancellation contains background work.
**Acceptance:** healthy Calendar works while Drive is down and vice versa; combined
transcript preserves earlier results; zero arbitrary tool dispatch.
**Definition of done:** provider and transport compatibility gates pass on locked
dependencies, lifecycle measured, actual wiring documented.
**Documentation:** correct current MCP guide's injected/stdio distinction; update
conversation/model contracts and independent failure/timeout runbooks.

### D5 — Telegram and CLI conversational integration

**Objective:** use the same assistant for metadata queries and contextual/combined
requests while preserving authorization and memory isolation.
**Prerequisites:** D4 router/transcript; approved Drive audience; no content tool yet.
**Existing reuse:** `TelegramAdapter`, `ConversationResponder`, plain-text splitter,
CLI session, model factory, history store, `MemoryService` owner identities.
**New components:** `pam/conversation/file_context.py`, Drive conversational tests,
shared conversation construction helper in the existing factory.
**Existing modifications:** `service.py`, `store.py`/models for provenance/bounds,
`system_prompt.py`, `factory.py`, `cli.py`, `telegram/bot.py`; capability-aware
start/help text in `telegram/adapter.py`. Memory SDK implementation stays generic.

**Responsibilities/data contracts:** intent exposure policy offers Calendar for
schedule questions, Drive for explicit file tasks, both for combined requests;
the model chooses among exposed tools, but registry validates every choice.
Low-confidence intent or an ambiguous referent prompts clarification. File context
maps displayed candidates to owner/session-scoped IDs and query-bound cursors.

**Tasks in order:**

1. Wire one shared conversation composition function into CLI/bot, with Drive
   optional and Calendar initialization independent; no API reads in the adapter.
2. Add intent/capability policy and prompt rules without weakening Calendar
   candidate-slot/presentation constraints. File content cannot supply event truth.
3. Store at most 50 references/session, with a 30-minute TTL and history-session
   capacity bound; clear on `/new`, account/grant change and eviction. Resolve
   duplicate names by candidate selection, never guess "that document".
4. Enforce account-owner/audience policy before Drive discovery and invocation.
   Revalidate metadata/permissions on each retrieval; reference membership alone
   does not grant access. Validate recognized Google links to IDs locally and
   never fetch arbitrary link URLs or use them to choose credentials.
5. Close passive memory leakage before enabling any Drive operation: conservative
   initial policy marks a session Drive-sensitive after a Drive request/result and
   suppresses automatic ingestion and durable recall queries from subsequent
   context-dependent turns until `/new`. Do not send Drive-derived user queries
   to Supermemory. Safe sanitized provenance filtering can replace suppression
   only after review and multi-turn tests prove the same guarantee.
6. Keep raw tool text/transcripts ephemeral; bound saved answer/history characters
   and maintain untrusted provenance across follow-ups. Explicit user-written
   `Remember <specific fact>` remains supported; do not resolve "remember this
   document" into a document save or allow model/tool content to invoke memory.
7. Preserve per-owner locking and clear/eviction behavior, including new file
   state and ingestion suppression; keep CLI owner distinct from Telegram.
8. Add metadata source references, clarify partial results, and update help only
   for enabled authorized capabilities. Combined replies retain deterministic
   Calendar facts when Drive fails and vice versa.

**Unit tests:** intent examples, Calendar-relative dates, duplicate names, stale/
cross-owner references/cursors, unsafe links, TTL/capacity, `/new`, authorization
before I/O, metadata-only Drive descriptions, combined partial failures.
**Integration tests:** real fake-backed Calendar+Drive router with scripted
provider and Telegram adapter/CLI composition; unauthorized/group requests
produce zero discovery/API/provider calls. Regression sequence: Drive result →
no-tool follow-up → ordinary answer → explicit Remember → `/new`; assert no
automatic Drive-derived ingestion or recall-query leakage at any step.
**Errors:** missing referent asks for clarification; stale/deleted IDs require a
new lookup; healthy combined answer is retained with specific unavailable source.
**Security:** no per-user Google-account claim; authorization and memory owners
unchanged; no inference-based raw document persistence.
**Acceptance:** authorized metadata queries and follow-ups work in both transports;
Calendar-only behavior passes existing gates; memory leakage tests pass before D6.
**Definition of done:** session lifecycle/privacy policy proven, finite state and
context sizes, both transports use the same reviewed routing contract.
**Documentation:** Telegram/CLI capabilities, audience warning, `/new` semantics,
history limits and revised memory ingestion policy.

### D6 — Safe file-content retrieval and summaries

**Objective:** retrieve supported content for user-requested summaries with
bounded provider context, untrusted-data handling and verifiable citations.
**Prerequisites:** D5 security/memory gate; approved content scope and explicit
consent/policy for hosted model transfer; D4 accumulated exchanges and limits.
**Existing reuse:** Google SDK download/export facilities, Drive service/models,
provider tool-response channel, router, authorized transports and logging.
**New components:** content retrieval/passage extraction within `pam/drive`,
strict content MCP tool schema, `pam/tests/test_drive_content.py`.
**Existing modifications:** Drive adapter/service/models/tools, provider serializer,
router/intent policy and prompt; no Calendar presentation changes.

**Responsibilities/data contracts:** service owns MIME/export allowlist and
resource bounds; provider receives only bounded `FileContent` passages with
untrusted provenance/source labels, never credentials or raw download URLs.
Summaries are generated in conversation, not a model embedded in the Drive server.

**Tasks in order:**

1. Support `application/vnd.google-apps.document` exported as `text/plain`, and
   uploaded `text/plain` decoded as strict UTF-8 (optional BOM). Metadata remains
   available for other types, with a clear content-not-supported answer.
   Sheets/Slides, PDF/DOCX, images, archives, executables, OCR and shortcuts are
   unsupported for content in this first release. Add formats only by explicit
   allowlist/parser review and a separate tested limit contract.
2. Recheck metadata, MIME and `capabilities.canDownload`; reject restricted,
   trashed or unsupported content. Never bypass copy/download restrictions.
3. Implement Google Docs `files.export` and plain-text media read with bounded
   streaming/chunks and transport timeouts; stop oversized transfer before
   whole-file allocation. Google export limit is separate from PAM's lower cap.
4. Validate encoding/content, strip unsafe display controls, and generate stable
   numbered text passages, source ID/name/link and modified-time stamp. Plain-text
   export does not preserve PDF page numbers or rich document layout; cite passage
   labels and source document, never fabricated page/section numbers.
5. Enforce byte, extracted-character, total-turn and provider-token limits before
   generation. Reject oversized files initially rather than silently truncating;
   if bounded excerpt mode is later approved, set truncation/coverage explicitly
   and never present it as a whole-document summary.
6. Add `drive_get_file_content` only to the approved server/router allowlists.
   Mark content/name/metadata as untrusted tool data structurally; prompt warns
   against following embedded instructions. Content cannot add tools, change
   auth/memory state, fetch links, run code, or trigger unrelated API operations.
7. Keep summaries confined to the requested task and sources; include verified
   citation links/labels from host-owned metadata. Validate output references
   against retrieved source IDs and report unsupported citations safely.
8. Test prompt injection and delayed memory leakage across follow-ups, errors,
   quotes, and combined requests; keep content out of stdout logs, disk caches,
   durable history stores and Supermemory. Bounded in-memory summary history is
   still Drive-sensitive context and follows D5 suppression rules.

**Unit tests:** MIME/export allowlist, missing size/canDownload, UTF-8/BOM/error,
stream stopping at cap, text/passages/token budget, no binary fallback, malformed
content, safe control characters, source URL/citation validation, injected text.
**Integration tests:** fake chunked media/export through real MCP/router/provider
serialization; multiple results retained through search → metadata → content →
Calendar; hostile documents cannot cause unauthorized API/memory calls. Later
test-account Google Doc/plain-text/oversized/denied fixtures and a BharatCode
summary with approved nonsensitive content only.
**Errors:** distinguish unsupported type, denied download, content too large,
malformed text, export failure, timeout and provider failure; no fabricated summary.
**Security:** data-transfer consent and provider retention review precede exposure;
read-only API plus scoped router authority enforce limits even when a model follows
injection. Prompt wording alone is not a complete defense.
**Acceptance:** supported summaries cite actual sources; unsupported/oversized
content fails safely; no automatic durable persistence or unexpected calls.
**Definition of done:** data-flow/memory/injection tests pass, content caps measured,
hosted transfer approved and first-release formats documented accurately.
**Documentation:** content formats/export limits, privacy/data transfer, citations,
partial-content behavior and safe errors; update memory guide with regression case.

### D7 — Live acceptance and production rollout

**Objective:** demonstrate Calendar safety, Drive utility and bounded VM impact,
then release through the existing single polling worker with a proven rollback.
**Prerequisites:** D1–D6 gates, architecture/OAuth/model-transfer approvals,
protected test credentials and fixtures, known-good release/credential backup.
**Existing reuse:** CI gates, production PM2/uv process/runbooks, Telegram smoke
checks, read-only Calendar acceptance and owner-isolated memory verification.
**New components:** acceptance evidence/checklist and Drive monitoring categories;
optional opt-in live harness only if required, never default network CI tests.
**Existing modifications:** deployment/testing/Drive docs and reviewed future
settings/credential provisioning. No new PM2 service, public listener or indexer.

**Responsibilities/data contracts:** release owner records commit, locked SDKs,
granted scopes, pass/fail evidence, measured limits and rollback reference without
secrets, personal filenames, document contents or account identifiers.

**Tasks in order:**

1. Run existing full offline quality gates plus Drive/router/content additions:
   `ruff format --check .`, `ruff check .`, `mypy pam`, `pytest`, link validation,
   `git diff --check`; use locked environment. Any future dependency change must
   update/review lockfile and pass both Windows development/Linux deployment.
2. Perform protected live OAuth acceptance: grants/refresh, partial/denied consent,
   reconnect, safe replacement, Calendar before/after; verify proposed grant
   separation experimentally in a test account without revoking production.
3. Verify Drive search/list/metadata, paginated/ambiguous/deleted files, Docs and
   plain-text summaries/citations, oversized/unsupported/denied content, rate-limit
   simulations, unavailable Drive/Calendar and combined partial answers.
4. Verify same bot/CLI account policy, private allowlist, separate memory owners,
   `/new`, multi-turn no-ingestion, explicit Remember/Forget and deterministic
   Calendar specific-time/candidate-slot behavior. Use one bot poller only.
5. Measure cold/warm discovery, API/model latency, process count, cancellation,
   RSS/CPU/swap, concurrent requests and repeated-turn leaks on the target VM.
   Set a documented headroom target from measured existing worker usage; no VM
   RAM size is inferred from the swap size. Reject rollout if finite caps do not
   preserve Calendar responsiveness or child processes accumulate.
6. Install reviewed release with `uv sync --locked --extra dev`, provision only
   distinct protected Drive credentials, keep Drive disabled initially, run
   Calendar smoke test; enable Drive for the operator after checks pass.
7. Restart only existing `pam-telegram`, verify PM2/log categories, authorized
   Telegram and memory acceptance. Validate startup/systemd/reboot restoration
   and ensure no OAuth HTTP service remains exposed or continuously running.
8. Execute rollback rehearsal: disable Drive and restart worker; verify Calendar.
   For code rollback restore the known-good release/lock state and prior safe
   config. Preserve Calendar credentials; restore them only if an approved
   migration changed them. Token revocation is not undone by Git rollback:
   reauthorization may be needed if a grant was invalidated.

**Unit tests:** no substitute for live acceptance; all earlier stage and current
Calendar/provider/memory/Telegram regression tests must pass.
**Integration tests:** offline full stack and opt-in protected Google/BharatCode/
Telegram acceptance above; failure injection and measured Linux process lifecycle.
**Errors:** on rollout failure disable Drive first; diagnose server-specific safe
categories; never log response bodies to troubleshoot.
**Security:** minimal operator audience, secured token/metadata paths, secret-free
logs/evidence, no second poller and no automatic document persistence.
**Acceptance:** checklist in section 10 passes with recorded evidence and tested
rollback. **Definition of done:** reviewed release stable on VM, Calendar and
memory intact, bounded resource usage, rollback/runbooks proven.
**Documentation:** production guide, testing/operations runbooks, configuration
names, Drive acceptance evidence and corrected architecture/conversation guides.

## 8. OAuth and security considerations

### Scope and consent decision

For account-wide read-only search plus content, proposed scope is
`https://www.googleapis.com/auth/drive.readonly`. For a metadata-only rollout,
consider `drive.metadata.readonly` and request content consent only at D6.
Both are restricted scopes. `drive.file` is non-sensitive and limited to files
opened/shared with the app, but includes write permissions and does not enable
arbitrary existing-file account-wide search. A user pasting a file ID is not a
Picker authorization grant. Do not silently substitute it for the approved
read-only/search contract. Do not request both metadata and full read scopes when
the broader approved read scope already satisfies the contract. These scope
tradeoffs follow [Google's scope guide](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

Before implementation signoff, determine internal/external audience, testing vs
production status, and applicable verification/security-assessment requirements.
Google documents additional requirements for restricted scopes, including server
storage/transmission. Azure retrieval and BharatCode transfer must be included in
that review; encryption and read-only tools do not exempt them. Record whether
PAM qualifies for any personal/internal-use exception; do not assume one. Review
provider use/retention and Google user-data policies before content transfer.
Sources: [Drive authorization requirements](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
and [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy).

Google supports incremental consent and access to multiple APIs under a grant;
this does not provide independently revocable Calendar/Drive grants automatically.
Use [web-server OAuth guidance](https://developers.google.com/identity/protocols/oauth2/web-server)
to implement granted-scope checks, offline refresh, denial handling and safe
reauthorization. External apps in Testing can have seven-day refresh-token expiry
for these scopes; repeated consent/token creation can invalidate earlier tokens.
Plan reconnect operations and avoid repeatedly forcing consent on normal reads.
Source: [OAuth token lifecycle](https://developers.google.com/identity/protocols/oauth2).

### Content, metadata, and persistence boundary

Only content required by an authorized user's request may reach BharatCode.
Explain this transfer during Drive setup and require review approval before D6;
never silently upload an entire Drive or pass credentials. Keep Google Docs
exports in-memory and bounded. `files.export` has a 10 MB upstream limit;
PAM's proposed 1 MiB transfer cap is deliberately lower. Downloads also require
checking download capability. Sources: [export reference](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export)
and [download/export guide](https://developers.google.com/workspace/drive/api/guides/manage-downloads).

Use structural tool responses and host-enforced capabilities for injection
resistance. Treat model output as untrusted too: a document instruction to
"remember all this" cannot reach memory actions; URLs cannot launch fetches;
file titles cannot influence registry identity. Reject citation sources absent
from verified results. Do not log query strings, file IDs/resource keys, names,
passages, provider payloads, or callback parameters. Prefer server/tool category,
approved error code, counts, duration, byte totals and non-reversible identifiers
only when necessary for operations.

The conservative D5 ingestion suppression covers metadata as well as content;
document names and summaries may be private. `/new` clears transient Drive
references/history/policy state, not the Google grant or existing durable user
memories. Explicit Remember saves only specific user-supplied content; raw Drive
document imports and automatic resolution of contextual Remember are excluded.

## 9. Deployment impact and risk register

Keep existing Azure/PM2 architecture and one Telegram poller. Proposed Drive
stdio children are temporary, bounded and supervised by the conversation client,
not independent PM2 services. Calendar's current injected wiring stays compatible;
any later transport consolidation requires explicit tests rather than a package
rename. No public ports, reverse proxy, database, vector index, or cron job needed.
Provision OAuth locally with a protected callback and transfer encrypted credentials
securely if required; do not add permanent FastAPI for the polling workload.

No new dependency is expected for Drive v3, Google Docs text export and UTF-8 text.
Actual locked SDK process/stream/cancellation semantics must be tested before
promising budgets. Large-file parsers or expanded formats require separate review.
Process-level credential separation must address `.env` loading and packaging
import paths as well as explicit child environment filtering.

| Risk | Mitigation / gate |
| --- | --- |
| OAuth changes overwrite Calendar token or aggregate/revoke grants | Distinct paths, dedicated Drive client recommendation, staged consent, granted-scope metadata, Calendar before/after live tests; review project boundary in D1. |
| Restricted scopes/hosted data transfer delay release | Decide scope/audience early; verify applicable policy/exception and provider data handling before D6. Metadata-only scope remains restricted. |
| Current interfaces mistaken for generic MCP/OAuth | Narrow extraction plus compatibility tests; preserve Calendar models/entry point; independent Drive adapters. |
| Multi-tool results lost or model emits several calls | Accumulated transcript, paired call IDs, deliberate sequential handling, bounded round count and combination tests. |
| Drive response leaks later through memory/history/query | D5 session suppression, no unsafe recall queries, bounded provenance-marked context, multi-turn spies on every memory call. |
| Allowlisted Telegram users see operator's private Drive | Owner-only initial Drive audience or explicit reviewed access policy; never claim per-user Google grants. |
| Injection changes instructions, causes exfiltration or false citations | Structural untrusted data, tool/access allowlists, no arbitrary network, source validation, hostile-document tests. |
| Drive/API failure disrupts Calendar | Independent initialization/discovery/deadlines/errors, partial results and failure matrix. Shared provider outage remains shared and is reported honestly. |
| Pagination misses or overclaims results | Empty-page handling, cursor binding, incomplete-search disclosure, no unbounded scan; [files.list contract](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list). |
| Rate limit / VM exhaustion / blocking SDK calls | Reason-based bounded retry and deadlines, byte/concurrency caps, measured Linux lifecycle/RSS/swap; [Google error guide](https://developers.google.com/workspace/drive/api/guides/handle-errors). |
| File changed/deleted or permissions removed between calls | Metadata revalidation on read, modified-time citation, safe stale-reference/error response; no claim of a transactional snapshot. |
| Credential file write crash or wrong permissions | Atomic safe replacement, validation/backups, protected metadata/token files and no Calendar-format migration by default. |
| Filtered subprocess env still reads all secrets from `.env` | Controlled child settings/env-file behavior and cwd, minimal secret sets, process-environment tests in D4. |
| Documentation drift or rollback cannot restore grants | Source-backed wiring docs, release/config backups, revoke only deliberately; reauthorize when needed. |

## 10. Acceptance checklist

### Planning deliverable (this task)

- [x] Actual repository baseline and audit limitations recorded.
- [x] Exact Calendar MCP, client, provider, OAuth, memory, tests and startup audited.
- [x] Same-repository independent Drive package/entry point proposed.
- [x] Reuse versus required changes documented without generic-interface assumptions.
- [x] Ordered D0–D7 objectives, prerequisites, components, tasks, contracts, tests,
  errors, security, acceptance, definitions of done and documentation included.
- [x] OAuth, trust, deployment, resource, memory and rollback risks addressed.
- [x] Review decisions distinguished from implemented behavior.
- [x] No final architecture diagram, implementation, commits, push or deployment.

Documentation links and `git diff --check` are validated as the final task checks;
their execution result is reported with the changed-file/status summary.

### Implementation/release gates (future, unchecked)

- [ ] Architecture review decisions and D0 contract approved.
- [ ] Calendar tool name/schema/result/presentation behavior preserved.
- [ ] Drive disabled by default; Calendar-only startup unaffected by Drive configuration.
- [ ] Independent Drive server allowlist and schema/stdio tests pass.
- [ ] No Calendar domain imports from Drive, no write/auth/generic fetch tools.
- [ ] Grant/scopes/verification policy and hosted transfer approved; live OAuth passed.
- [ ] Calendar file/grant protected through Drive provisioning, denial and rollback.
- [ ] Tool names unique; schema/result checks and fixed server routing enforced.
- [ ] Sequential accumulated transcript works for combined requests and both providers.
- [ ] Calendar-down/Drive-down/discovery/call failure matrix preserves healthy work.
- [ ] Unauthorized/group users trigger zero discovery/reads; Drive account audience explicit.
- [ ] References/cursors/history bounded, owner-isolated, evicted and cleared by `/new`.
- [ ] Drive-derived data never automatically enters Supermemory, even on later turns.
- [ ] Supported format/size/encoding/download checks and verified citations pass.
- [ ] Injection cannot grant tools, invoke memory, fetch arbitrary URLs or expose secrets.
- [ ] Offline quality gates and protected live Telegram/CLI/regression acceptance pass.
- [ ] Azure latency/resources, cancellation and child cleanup measured within approved limits.
- [ ] Single poller/PM2 startup/reboot and feature-disable/code rollback rehearsed.
- [ ] Docs match released behavior and safe monitoring/runbooks are available.

## 11. Open design decisions for architecture review

These are implementation gates, not gaps hidden behind a claim of readiness.

| Decision | Recommended starting position | Evidence needed / stage owner |
| --- | --- | --- |
| Repository/packages | Single repository, `pam.drive` with independent MCP; preserve legacy Calendar paths. | Approve boundary and no Calendar domain dependency in D0. |
| Scope rollout | `drive.readonly` for approved account-wide read+summary; metadata-only first grant if content consent is deferred. | Confirm required search reach, scope necessity and restricted-scope review in D1; no Picker assumption. |
| Google grant isolation | Dedicated Drive OAuth client and separate token path; assess consent/project separation if independently revocable grants are required. | Test actual aggregation/revocation and confirm audience/exceptions before D1 signoff. |
| Credential metadata format | Separate protected versioned Drive grant record; keep Calendar token format. | Select envelope vs sidecar, account binding and atomic update behavior in D1. |
| Drive audience | Account owner only initially, even when Calendar has more allowlisted users. | Approve policy and where enforced before D5; per-user OAuth stays out of scope. |
| Transport/lifecycle | Drive on-demand stdio; current Calendar injected path remains; no permanent new services. | Validate locked SDK env/cancellation/cwd behavior and resource cost in D4/D7. |
| Tool transcript/budget | Sequential calls, accumulated exchanges; six-call Drive/combined ceiling, two for Calendar-only. | Provider/schema compatibility and search→metadata→content→Calendar tests in D4. |
| Passive memory exclusion | Conservative Drive-sensitive session ingestion/recall suppression until `/new`. | Accept reduced passive memory behavior; prove multi-turn no-leak tests in D5. A finer provenance filter needs separate proof. |
| Content/model transfer | Google Docs/plain UTF-8 text only, bounded and requested; no large/binary parsers. | Approve provider data handling/consent and Google policy before D6. |
| Shared drives and shortcuts | Personal user corpus; shortcuts metadata-only. | Confirm whether first-release user needs require shared drives; otherwise exclude, document explicitly in D2. |
| Bounds/performance | Section 6 starting caps; no unbounded persistence or background index. | Approve token cap strategy, VM headroom/latency target and measured limits in D4/D7. |
| Citation/partial content | Source link plus numbered export passages; reject oversized files initially. | Approve output verification and user-facing partial-result wording in D6. |

## 12. Documentation update map

During this task: create this plan and add one link to [Docs index](../README.md).
Later approved implementation stages should update [Architecture](../ARCHITECTURE.md),
[MCP integration](../MCP_INTEGRATION.md), [Conversation and models](../CONVERSATION_AND_MODELS.md),
[Calendar integration](../GOOGLE_CALENDAR_INTEGRATION.md),
[Memory integration](../MEMORY_INTEGRATION.md), [Telegram integration](../TELEGRAM_INTEGRATION.md),
[Production deployment](../PRODUCTION_DEPLOYMENT.md),
[Testing and operations](../TESTING_AND_OPERATIONS.md), and [Roadmap](../ROADMAP.md),
plus a focused Drive guide and safe configuration-name reference. D0 approval
precedes any final architecture diagram; that diagram remains separate work.
