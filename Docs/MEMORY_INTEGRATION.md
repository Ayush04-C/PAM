# Supermemory integration

## Purpose and ownership

PAM optionally uses Supermemory for long-term preferences and facts. It is enabled with `PAM_MEMORY_BACKEND=supermemory`; `disabled` provides safe no-op recall/passive ingestion and makes explicit Remember/Forget report failure rather than claim success.

Each logical owner is isolated with an opaque container tag derived from a SHA-256 hash of the owner identifier. The raw owner ID is not sent as the container tag. CLI uses the configured `PAM_MEMORY_CLI_OWNER_ID`; Telegram uses the authenticated user ID, so one Telegram user cannot recall or forget another user's container. Default direct service usage derives an owner from the session.

## Operations

| Operation | Trigger | Supermemory use | PAM behavior |
| --- | --- | --- | --- |
| Recall | Ordinary user message | Hybrid memory search in the owner's container | Returns bounded items/characters as untrusted model context. |
| Explicit remember | `Remember …` | Explicit memory add with memory task metadata | PAM confirms only after success. |
| Explicit forget | `Forget …` | Exact, owner-scoped memory forget | Broad/empty requests are rejected safely; success removes future recall. |
| Passive ingestion | Successful ordinary non-tool turn | Conversation ingestion with an opaque conversation ID | Failures do not discard an already successful assistant response. |

PAM configures bounded recall with `PAM_MEMORY_MAX_RECALLED_ITEMS` and `PAM_MEMORY_MAX_CONTENT_CHARS`. It creates Supermemory's async client with a 15-second timeout and one retry. Treat those as service-client settings, not a guarantee of end-to-end response time.

## Trust and retention rules

Recalled content may contain inaccurate or adversarial text. Both model adapters label it as untrusted context, and it cannot add tools, reveal secrets, or override PAM's Calendar-only allowlist. The memory service logs only a hashed owner reference and limited operational metadata, not memory contents.

Calendar tool results are excluded from passive durable ingestion. This avoids persisting sensitive, time-sensitive live schedules and prevents stale availability from being treated as a user preference. When memory conflicts with live Calendar data, live Calendar data wins for the requested date.

## Failure policy

* Recall errors are swallowed so normal conversation remains available.
* Passive-ingestion errors are swallowed after a successful answer is returned.
* Explicit remember/forget errors return a failure message and never claim the action succeeded.
* An unavailable memory backend does not silently convert an explicit command into a successful response.

## Test coverage

Offline tests use fake persistent memory backends to verify owner isolation, update/supersession behavior, restart persistence independent of transient history, explicit remember/forget, `/new` behavior, bounded recall, injection resistance, and Calendar-over-memory precedence. Live Supermemory acceptance requires separately provisioned credentials and is not a substitute for the offline suite.

