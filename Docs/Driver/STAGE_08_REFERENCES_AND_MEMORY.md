# Stage 8: Drive references, transports and shared-memory boundaries

Stage 8 adds temporary verified file choices to the existing conversation store.
CLI and Telegram use one composition factory and the same routing rules. This
stage remains metadata-only; file contents belong to Stage 9.

## Implementation and limits

- `pam/conversation/file_context.py` holds the latest verified search page and
  its query-bound continuation. A new search/page replaces the displayed choices;
  metadata refreshes update existing choices without resetting their expiry.
- At most 50 references live in one session. They expire 30 minutes after the
  search/initial lookup. Session count and history count retain the existing
  configured LRU bounds. Reference state is evicted with its session and cleared
  by `/new` or process restart. There is no separate persistent file index.
- Successful answers that update references append a host-generated numbered
  list with canonical source links. Names are JSON-quoted, so embedded newlines
  cannot manufacture additional rows. This list defines the selection numbers;
  the provider is instructed not to invent or reorder its own numbered choices.
- Common selections include `file 2`, `the second one`, and a standalone `2`.
  `that file` resolves only when there is one choice. Duplicate names and unclear
  selections prompt clarification without a Google or model call. This is a
  deliberately small reference resolver, not a general natural-language parser.
- References are bound to owner, model destination and an opaque account/client/
  refresh-credential/scope fingerprint. The fingerprint is host-only, hidden
  from repr and never serialized to the model or Supermemory. Saved credentials
  need no migration. Changed identity or missing permission invalidates references;
  retained sensitive history still requires its original boundary or `/new`.
- Lookup still requires current read and model-transfer permission and a fresh
  metadata call. A model's plain answer cannot satisfy a selected-file lookup.
  File references are not credentials, permission caches or fresh facts.
- Only recognized HTTPS Drive/Docs/Sheets/Slides link shapes are parsed into IDs,
  entirely locally. Userinfo, explicit ports, lookalike hosts and arbitrary URLs
  are rejected as ID authority. No user URL is fetched. Raw explicit IDs retain
  the existing validated lookup path.
- Pagination requires the saved token's exact query and page size. An invalid
  cursor clears the saved continuation; an unavailable metadata lookup removes
  that file from the current choices on a successfully completed response.
- The existing Drive context character ceiling includes reference context and
  cumulative tool arguments/results. Six total calls and two Calendar calls
  remain the limits for Drive-enabled turns.

Only successfully completed turns commit new choices. A model failure does not
save a partially completed search. Expiry is enforced on access; there is no
background timer. Old sensitive history may remain after references expire,
but cannot authorize an expired ID or cursor. The existing service lock and
memory-conversation-ID bookkeeping are unchanged by this stage.

## Shared Supermemory policy

The existing memory backend and owner containers are reused. No second Supermemory
service, SDK, key or container scheme is introduced.

Automatic recall and ingestion remain suppressed for Drive-enabled turns and
retained sensitive history. Even no-tool answers and Drive discovery failures
retain a sensitive marker when current Drive transfer permission exists: the
user's filename itself may be private. `/new` clears this context; if Drive stays
enabled and authorized, new turns remain conservatively protected too.

Explicit `Remember I prefer short replies` saves only that user-written literal
through the existing backend, and confirms only after success. Contextual requests
such as `Remember the second file` cannot resolve references into durable saves.
Retrieved filenames cannot trigger Remember/Forget or create tool permissions.
Pasted literal text is not automatically classified as retrieved Drive data.

This stage does not authorize Drive data persistence or automatic document imports.
Any future persistence feature needs its own explicit data-transfer/retention
permission and tests. Sharing the backend does not grant such permission.

## CLI and Telegram acceptance

No new environment variable, dependency, Google scope or Cloud Console setup is
required. Existing OAuth and explicit metadata-transfer consent still apply.
Review and enable that permission using the existing
[Stage 7 provisioning steps](STAGE_07_ROUTING.md#cli-setup-and-verification)
only if you approve sending metadata to your configured model destination.

From the repository root:

```powershell
.venv\Scripts\python.exe -m pam.conversation.cli --status
.venv\Scripts\python.exe -m pam.conversation.cli
```

Try:

```text
/help
Find PAM TEST.
Show metadata for file 1.
Show metadata for that file and check my Calendar availability tomorrow.
/new
Show metadata for that file.
```

Expected: search/lookup responses show verified choices and source links; the
selected lookup refreshes metadata. After `/new`, the old reference needs a new
search or explicit recognized link. For multiple results, try `2`; for ambiguous
`that file`, expect a numbered clarification. `Next page` uses the saved search
only while its continuation exists. Limited/incomplete results are disclosed.

Telegram uses the same factory, with the existing private-chat/allowlist checks
before help or conversation work. `/start` and `/help` mention Drive only when
the authenticated owner has current metadata-transfer permission. Help checks
local configuration/grants, not live Google/MCP connectivity. CLI supports
`/help`, `/status` and `/new`; Telegram supports `/start`, `/help` and `/new`.

Single-owner provisioning is unchanged. A `cli-local` grant does not authorize
`telegram:<user-id>`. This stage adds no account onboarding or owner remapping.

## Errors, tests and checkpoint

| Case | Behavior |
| --- | --- |
| Unknown, expired or out-of-range selection | Clarify; do not guess from old history |
| Different owner reuses a session | Deny before provider, discovery or memory recall |
| Grant/account/credential/destination changes | Invalidate choices; block incompatible sensitive history |
| File unavailable or cursor rejected | Drop stale choice/continuation on successful completion; request a new search |
| Model substitutes another ID | Reject before lookup |
| Model skips selected-file refresh | Return a safe failure instead of its unverified answer |
| Oversized reference context | Stop before model/memory work; suggest `/new` and a narrower search |
| Model/API/memory outage | Preserve existing bounded errors and Calendar partial-answer behavior |

`pam/tests/test_drive_references.py` adds 43 offline cases covering selections,
links, expiry/capacity/LRU/reset, owner/session/grant isolation, pagination,
freshness, invalidation, incomplete results, context limits, private fingerprints,
CLI/Telegram flows, denied/group access and multi-turn memory suppression.
Existing routing tests now expect the verified source footer.

Full validation: 451 tests, Ruff lint/format, strict mypy and documentation links.
Tests use fake Google, scripted models and fake memory; no real provider,
Telegram or Supermemory requests are needed. Live hosted-model acceptance remains
pending explicit operator transfer permission. No local credentials, `.env`,
permissions or Google Cloud settings were modified.

Next is Stage 9: bounded, explicitly authorized supported-file content reads.
