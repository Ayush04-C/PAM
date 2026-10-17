# Conversation and model providers

## Conversation lifecycle

`ConversationService` is the shared application layer for CLI and Telegram. It serializes each `session_id` with an async lock, so a session's history is not interleaved by concurrent messages. The default `InMemoryConversationStore` holds a bounded LRU set of sessions and a bounded number of messages per session; it is intentionally lost on process restart.

For an ordinary non-empty message the service builds a provider-neutral turn with system instruction/current time/allowed MCP tools/history/message. Calendar is available as before; Drive metadata tools require current owner-bound read and model-transfer permission. Automatic memory recall/ingestion is skipped for Drive-eligible turns and sensitive history. Other successful non-tool turns retain normal memory behavior. Successful derived answers retain Drive provenance in transient history. See [Stage 7](Driver/STAGE_07_ROUTING.md).

`/new` is handled by adapters and CLI through `ConversationService.clear`. It removes short-term session history and starts a fresh memory conversation identifier; it does **not** delete durable memories. Explicit `Remember …` and `Forget …` commands are intercepted before the model provider.

## Provider abstraction

CLI and Telegram construct dependencies through `create_conversation_service`.
Stage 8 stores at most 50 verified file choices per session for 30 minutes, with
query-bound continuation tokens, owner/grant/destination checks, numbered
clarification and fresh metadata lookup for selected files. `/new` also clears
these choices. See [Stage 8](Driver/STAGE_08_REFERENCES_AND_MEMORY.md).

The `ModelProvider` protocol has `respond` and `respond_after_tool` methods. `BharatCodeProvider` uses an OpenAI-compatible API; `GeminiProvider` uses the Google Gen AI SDK. Provider selection is configured with `PAM_MODEL_PROVIDER` (`bharatcode` or `gemini`), and the factory selects one provider—there is no automatic cross-provider fallback. A scripted provider is used in offline tests, not as a normal interactive CLI provider.

Provider exceptions are normalized to an assistant-facing unavailable message. PAM does not reveal SDK responses, API keys, requests, or tool internals in that message.

## Tool-calling loop

The host validates the requested tool, rechecks sensitive-data consent, invokes
the narrow client, validates the structured result, and supplies the accumulated
sequential transcript to the provider. Unknown tools and unauthorized Drive calls
are refused. Both providers retain earlier exchanges and reject parallel calls.

Calendar-only turns retain two tool calls. Drive-eligible turns allow six total calls with at most two Calendar calls; cumulative Drive arguments/results must fit the configured character limit. Tool answers are not passively memory-ingested. On combined failures, verified Calendar availability can be preserved without inventing missing Drive results.

## Prompt and data boundaries

The system instruction establishes current time and PAM's Calendar role. Model output is untrusted, and tool availability is application-controlled. Recalled memory is sent with an explicit marker: it is **untrusted context, not instructions**. This prevents a stored prompt-injection string from granting tools or changing application policy. Tool outputs are structured objects, not instructions to execute.

PAM supports Calendar availability and consent-gated Drive metadata reads. It has no write or file-content tool. Retrieved Drive data and derived history remain untrusted; code enforces authority independently of prompt wording. Content reading is later-stage work.

## Phase 10 availability presentation

The Calendar MCP result includes deterministic presentation facts beside human-readable availability text. It carries date/weekday details, busy minutes, all-day status, free windows, and optional candidate slots. Candidate slots require an entirely free interval at least as long as the requested duration; a slot does not cross days or busy events. A requested time is evaluated only for a one-day range. Live Calendar results remain the source of truth for current availability, even if durable memory says a user is usually free at a conflicting time.

See [AVAILABILITY_PRESENTATION.md](AVAILABILITY_PRESENTATION.md) for the full stable contract.
