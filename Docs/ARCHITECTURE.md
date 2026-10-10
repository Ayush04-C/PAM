# Architecture

## System overview

PAM is a Python 3.12 assistant. CLI and Telegram input reaches `ConversationService`, which asks the configured model provider for a reply. A provider may request the single approved Calendar tool. PAM invokes a private local MCP client/server pair and returns the structured result to the provider. PAM can also recall and ingest durable user memory through Supermemory. FastAPI exposes health, availability, and local Google OAuth endpoints; it is not the Telegram transport.

```mermaid
flowchart TD
    CLI[CLI] --> CS[ConversationService]
    TG[Telegram polling adapter] --> CS
    CS --> MP[Configured model provider: BharatCode or Gemini]
    CS --> MC[CalendarMcpClient]
    MC --> MS[Local MCP server over stdio]
    MS --> AS[AvailabilityService]
    AS --> CR[CalendarReader]
    CR --> GC[Google Calendar API]
    CS --> MEM[MemoryService]
    MEM --> SM[Supermemory]
    HTTP[FastAPI] --> AS
    HTTP --> OA[Local Google OAuth routes]
    OA --> GC
    OA --> CSF[Encrypted credential store]
    CR --> CSF
```

### Component responsibilities

| Component | Responsibility | Important boundary |
| --- | --- | --- |
| CLI / Telegram adapter | Converts input to a session and memory owner; renders a text response. | Neither adapter calls Google directly. |
| `ConversationService` | Serializes a session, recalls memory, runs the bounded provider/tool loop, commits transient history, and handles `/new`. | It permits only `get_weekly_availability`. |
| BharatCode / Gemini adapters | Convert provider SDK requests/responses to provider-neutral model types. | Provider output is untrusted. |
| `CalendarMcpClient` and local MCP server | Discover and execute the one Calendar MCP tool over local stdio. | MCP is private, not an Internet-facing Calendar API. |
| `AvailabilityService` | Validates date range policy and calculates deterministic free/busy availability. | It maps reader failures to `CalendarUnavailable`. |
| `CalendarReader` | Reads primary-calendar events through the configured backend. | Google credentials stay below this layer. |
| Credential store | Encrypts only the OAuth refresh credential at rest with Fernet. | It never returns a credential to HTTP responses. |
| `MemoryService` | Bounded recall, explicit memory actions, and passive conversation ingestion. | Recalled content is untrusted context. |

## Availability request flow

The FastAPI endpoint is direct; the conversational route has the same availability service behind MCP.

```mermaid
sequenceDiagram
    participant U as Caller
    participant API as FastAPI or ConversationService
    participant MCP as Local Calendar MCP
    participant AV as AvailabilityService
    participant R as CalendarReader
    participant G as Google Calendar
    U->>API: request range and timezone
    alt conversational request
        API->>MCP: get_weekly_availability(validated arguments)
        MCP->>AV: get_structured_availability
    else HTTP POST /availability
        API->>AV: get_weekly_availability
    end
    AV->>R: list events in range
    R->>G: events.list(primary, read-only)
    G-->>R: event pages
    R-->>AV: normalized events
    AV-->>API: deterministic availability and presentation facts
    API-->>U: text or JSON response
```

`AvailabilityService` clips and merges busy intervals. Phase 10's presentation builder supplies stable dates, free windows, candidate slots, and weekly facts. Candidate slots are factual intervals, not promises that an event can be created; Calendar writes are unsupported. See [AVAILABILITY_PRESENTATION.md](AVAILABILITY_PRESENTATION.md).

## Memory lifecycle

```mermaid
sequenceDiagram
    participant U as User
    participant C as ConversationService
    participant M as MemoryService
    participant S as Supermemory
    participant P as Model provider
    U->>C: ordinary message or Remember/Forget request
    alt ordinary message
        C->>M: recall(owner, message)
        M->>S: hybrid memory search in owner container
        S-->>M: bounded recalled items
        M-->>C: untrusted memory context
        C->>P: system prompt, history, untrusted memory, message
        P-->>C: response or approved tool call
        C-->>U: assistant response
        C->>M: passive ingestion after successful non-tool turn
        M->>S: conversation ingestion
    else explicit memory action
        C->>M: remember or forget scoped to owner
        M->>S: explicit memory API operation
        M-->>C: success or failure
        C-->>U: truthful confirmation or failure message
    end
```

## Trust boundaries and data flow

* **User input, model output, recalled memory, and remote API responses are untrusted.** Model requests cannot select arbitrary tools; memory is labelled untrusted context in provider prompts.
* **The Calendar tool is read-only.** Its MCP schema rejects extra or malformed inputs, and `ConversationService` rejects every tool name except the one allowlisted name.
* **OAuth secrets and refresh credentials are sensitive.** Environment values provide OAuth client configuration; the refresh credential is encrypted locally and is not logged or returned by OAuth routes.
* **Session history is transient.** The default store is in-memory and `/new` clears it. Durable memory is separate and can survive a new store instance.
* **Logging is structured and redacted.** Request IDs support correlation; operators should not add prompts, credentials, tokens, or provider payloads to logs.
