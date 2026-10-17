# Stage 2: Consent and LLM boundaries

This stage adds a deny-by-default boundary to the existing conversation flow.
It does not connect Google Drive, collect real consent, or register Drive tools.
Both Calendar and Drive are planned capabilities of the same MCP server; only
the tools needed for an authorized request will execute. Neither capability will
require the other's credentials. Calendar is the only implemented MCP tool today.

## Permissions and data flow

Trusted host code supplies a `DriveConsent` for a specific `MemoryOwnerId` and
model destination. Its three permissions default to false: Google reads,
standalone metadata transfer, and document-content transfer. Content permission
includes content-derived summaries; it does not authorize standalone metadata
reads/transfers automatically. A content result may include its associated source
metadata. No natural-language message, model output or document can create consent.

`require_read(owner)` is the check future Drive API code must call before I/O.
Google OAuth grants remain a separate prerequisite. This stage has no Google-read
implementation and therefore cannot prove that future adapter integration yet.

The existing `ConversationService.respond` now accepts optional internal
`drive_context` and `drive_consent` arguments. Missing permission, wrong owner,
wrong destination or an unknown destination rejects tagged context before model,
tool discovery or automatic memory calls. Context is limited to 20,000 characters.
The caller must supply only approved file text/metadata, never OAuth tokens or
configuration secrets. The normal Telegram/CLI text interface cannot populate
these internal arguments from model-generated JSON or grant consent itself.

Both adapters serialize authorized context as a separate, explicitly untrusted
user-data message, never as system instructions. The API key is not in the model
turn. Instructions say reads only, no credential disclosure or document-directed
tool/memory actions, and no invented Drive support. The service also filters tool
discovery and execution to its currently implemented Calendar allowlist. Drive
tools remain blocked until the later dispatch/server stage adds validated reads.

Destination identity includes provider and model, plus the configured BharatCode
base URL. Gemini pins its normal Google API endpoint and disables implicit Vertex
routing, so an environment override cannot silently change a consented destination.
This is the configured target, not proof of a local inference deployment or of a
provider's retention practices. A new provider/routing mode needs a reviewed target
identity; providers without one cannot receive Drive context. No fallback exists.

## History, memory and failure behavior

Successful derived answers carry an owner/destination/data-kind marker in the
existing bounded in-memory history. Raw retrieved payloads are not committed to
history; summaries may quote them and remain sensitive. Every subsequent normal
turn inherits sensitivity, even after earlier messages are trimmed. It requires
fresh matching per-call consent and skips automatic Supermemory recall queries
and ingestion. Metadata and content permissions are rechecked for retained history.
Changed owner/destination or withdrawn consent fails safely without forwarding
history. `/new` discards transient history and markers; full session eviction also
discards that context. No separate unbounded consent/session registry is added.
Any future custom `ConversationStore` must preserve these markers.

Specific user-written Remember/Forget requests remain explicit memory actions.
Passing retrieved context alongside a memory command is rejected; the model never
invokes memory actions. Unresolved references such as "Remember this document"
are rejected instead of implying a document save. Existing durable memories and
other owners are unchanged.
Failed model calls commit no new context/history and expose no payload details.
Denial messages explain the consent mismatch and `/new`; payloads are not logged,
and `DriveContext` also hides its text from its default object representation.

## Verification and limits

Stage tests are grouped in [permission values](../../pam/tests/test_drive_policy.py),
[provider serialization](../../pam/tests/test_drive_model_context.py) and
[conversation enforcement](../../pam/tests/test_drive_consent.py).
They cover independent read/transfer grants, metadata versus content, owner and
destination mismatch, revocation, bounded history, later no-tool turns, `/new`,
owner isolation, explicit memory, malicious instructions, discovery filtering,
provider failure, both serializers, the Gemini endpoint and secret-free payloads.
Existing Calendar, conversation, history, memory and Telegram regressions are reused.

The gate is format, lint, mypy, full offline tests, documentation links and
`git diff --check`. No live Google/model/Telegram calls or deployment are part of
this stage. Passing tests establish this host-supplied context path, not complete
prompt-injection resistance or an assurance about a model provider's data retention.

Validation on 2026-10-17: 188 tests passed, including 28 Stage 2 cases and the
revised shared-value import check. Format/lint/type checks passed. Existing async
tests ran outside the Windows sandbox to allow local event-loop sockets.
All 99 local documentation links/anchors and whitespace checks passed.

Later stages must add authenticated consent collection/revocation, check it before
real Drive reads, tag all retrieved results and derived history, enforce transfer
at the future tool-result boundary, and test combined requests end to end. Arbitrary
user-pasted text is not automatically classified as Drive data by this policy.
Byte/download/token budgets and supported file parsers remain retrieval-stage work.
Local and hosted inference both require explicit consent; locality is never assumed.
