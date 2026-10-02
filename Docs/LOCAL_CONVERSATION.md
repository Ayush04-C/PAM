# Local conversation testing

Phase 6 adds a single-turn conversational layer. It has one Calendar capability:
`get_weekly_availability`. The model never talks to Google Calendar directly.

```text
CLI -> ConversationService -> ModelProvider -> Calendar MCP
                                          -> AvailabilityService -> CalendarReader
```

## Configure Gemini

In the ignored `.env` file, set:

```dotenv
PAM_MODEL_PROVIDER=gemini
PAM_GEMINI_API_KEY=your-gemini-api-key
PAM_GEMINI_MODEL=gemini-2.5-flash
PAM_CONVERSATION_DEBUG_TOOL_CALLS=false
```

`gemini-2.5-flash` is configurable and is the default because it supports
function calling while targeting low-latency, price-conscious conversations.
The implementation uses the maintained `google-genai` package. Keep API keys
out of source control and do not place them in prompts, MCP requests, or logs.

## Run the CLI

With the virtual environment active and Gemini configured:

```powershell
.\.venv\Scripts\python.exe -m pam.conversation.cli
```

Ask one independent question per prompt and use `quit` or `exit` to leave. For
example: `How busy am I next Monday?`

For offline automated development, leave `PAM_MODEL_PROVIDER=fake`; the test
suite uses `ScriptedModelProvider` and a fake Calendar reader, and makes no
network or Gemini calls.

## Trust and privacy boundary

Gemini may receive the user question, the explicit Asia/Kolkata current time,
the approved MCP tool schema, and the structured availability result required
to answer the question. It does not receive OAuth client secrets, Google access
or refresh tokens, credential encryption keys, credential-store content, or the
Google API client.

MCP remains authoritative for schema and business validation. Model-produced
arguments are untrusted and are forwarded unchanged to MCP. Only the exact
read-only `get_weekly_availability` tool can run; unknown and write-like tool
names are blocked. PAM limits a turn to two tool rounds and treats event titles
and all tool values as data, never instructions.

## Manual verification

Use a local ignored `.env` with real Gemini and Google configuration. Start the
CLI and ask availability questions such as today, tomorrow, next Monday, and a
multi-day range. Confirm the local MCP tool is used by temporarily setting
`PAM_CONVERSATION_DEBUG_TOOL_CALLS=true`; it prints only `tool invoked:` and the
tool name. Compare a known range with the direct `/availability` API and direct
MCP result.
Do not save prompt or response dumps containing Calendar data.
