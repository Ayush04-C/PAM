# Supermemory local setup

Phase 9 adds optional durable, semantic user memory through Supermemory. It is
disabled by default, so existing CLI, Telegram, BharatCode, and Calendar use do
not need a Supermemory key.

## Enable it

Create an API key in the Supermemory console, keep it only in ignored `.env`,
and configure:

```env
PAM_MEMORY_BACKEND=supermemory
PAM_SUPERMEMORY_API_KEY=replace-with-your-key
PAM_MEMORY_CLI_OWNER_ID=my-local-development-owner
```

PAM uses the official `supermemory` Python SDK. It derives an opaque,
PAM-controlled `pam-user-<sha256>` container tag from each stable owner; the
model never chooses the container. Telegram uses the authorized numeric user ID and the CLI uses
`PAM_MEMORY_CLI_OWNER_ID`, so they remain separate unless you intentionally
configure the same owner.

## Behaviour and privacy

`Remember that ...` uses the SDK's document ingestion with `task_type="memory"`,
`dreaming="instant"`, and explicit fact-extraction context. This is
intentionally distinct from ordinary conversation learning: successful ordinary
turns use Supermemory's v4 conversation-ingestion endpoint with an opaque,
owner-scoped conversation ID. Each update sends the complete bounded,
role-tagged PAM history for that active conversation; `/new` starts a new
conversation ID rather than replacing an older source. `Forget that ...` sends
a scoped exact-content forget request. Failed model or Calendar turns are not
ingested. Calendar tool output is never sent directly to memory.

`/new` clears only Phase 8 recent in-memory conversation context. It does not
remove durable Supermemory data. Durable memory can therefore survive CLI,
Telegram, application, and machine restarts.

PAM recalls at most five memories of up to 500 characters each by default.
Recalled content is untrusted context, never system instruction. Current user
statements and live Calendar data take precedence over recalled memory.

Ordinary conversation extraction is asynchronous. PAM does not claim that a
natural preference has been durably saved just because the conversation upload
was accepted. It recalls formal extracted memories, plus the safe explicit-memory
document fallback; it does not inject raw conversation chunks because a chunk can
contain assistant text. For manual acceptance, wait until a memory-only search
can retrieve the natural preference before expecting a new conversation to use it.

Do not log, commit, or share API keys or memory dumps. To disable memory again,
set `PAM_MEMORY_BACKEND=disabled`.

## Manual verification

Run `python -m pam.conversation.cli`, then send `Remember that I prefer project
meetings after 5 PM.` Wait for Supermemory processing to complete, then run
`/new` and ask when you prefer project meetings. The preference must be present
in the subsequent model turn, not only accepted as a document upload. Repeat
after restarting the process. Test updates with a new preference and explicit
forgetting with `Forget that ...`.
