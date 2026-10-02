# Bounded conversation history

Phase 8 adds short-term, in-memory context that PAM—not Telegram, BharatCode,
Gemini, or MCP—owns. It stores only successful portable user/assistant text
exchanges. Raw tool calls and Calendar MCP results remain ephemeral within the
current turn and are not archived as history.

```text
transport session ID -> ConversationService -> InMemoryConversationStore
                                      -> provider request with bounded history
```

History is limited by individual messages, not turns:

```dotenv
PAM_CONVERSATION_MAX_HISTORY_MESSAGES=20
PAM_CONVERSATION_MAX_SESSIONS=100
```

When the message limit is exceeded, PAM discards the oldest messages first. The
latest messages are retained. The store also retains at most 100 least-recently
used sessions; adding another session evicts the oldest accessed session.

For Telegram, an authorized private user receives the opaque session identity
`telegram:<numeric-user-id>`. Authorization and private-chat checks happen
before the adapter can load, update, or clear its history. The CLI uses
`cli:local` for the life of one process.

Use `/new` in Telegram or the CLI to clear only the current session. `/start`
and `/help` do not clear history. History is in memory only: stopping and
restarting PAM starts fresh sessions. No history is exposed through HTTP,
commands, debug output, or default logs.

System instructions and current Asia/Kolkata time are rebuilt for every turn.
Stored history is untrusted context and cannot override the read-only Calendar
policy, tool allowlist, or MCP validation.
