# Local conversation testing

Phase 6 adds a single-turn conversational layer. It has one Calendar capability:
`get_weekly_availability`. The model never talks to Google Calendar directly.

```text
CLI -> ConversationService -> ModelProvider -> Calendar MCP
                                          -> AvailabilityService -> CalendarReader
```

## Configure BharatCode

In the ignored `.env` file, set:

```dotenv
PAM_MODEL_PROVIDER=bharatcode
PAM_BHARATCODE_API_KEY=your-bharatcode-api-key
PAM_BHARATCODE_BASE_URL=https://bharatcode.ai/api/model/v1
PAM_BHARATCODE_MODEL=deepseek-v4.1-flash
PAM_CONVERSATION_DEBUG_TOOL_CALLS=false
```

Use `python -m pam.conversation.bharatcode_models` to list the models enabled
for the local key. BharatCode uses its OpenAI-compatible `/chat/completions`
endpoint. Keep API keys out of source control and do not place them in prompts,
MCP requests, or logs. Gemini remains an explicit optional provider for local
comparison when `PAM_MODEL_PROVIDER=gemini`.

## Run the CLI

With the virtual environment active and a provider configured:

```powershell
.\.venv\Scripts\python.exe -m pam.conversation.cli
```

Questions share bounded in-memory context within the running CLI process. Use
`/new` to clear that local context, or `quit`/`exit` to leave; a restart begins
a fresh session. For example: `How busy am I next Monday?`

For offline automated development, leave `PAM_MODEL_PROVIDER=fake`; the test
suite uses `ScriptedModelProvider` and a fake Calendar reader, and makes no
network or Gemini calls.

## Trust and privacy boundary

The selected provider may receive the user question, the explicit Asia/Kolkata current time,
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

Use a local ignored `.env` with real BharatCode and Google configuration. Start the
CLI and ask availability questions such as today, tomorrow, next Monday, and a
multi-day range. Confirm the local MCP tool is used by temporarily setting
`PAM_CONVERSATION_DEBUG_TOOL_CALLS=true`; it prints only `tool invoked:` and the
tool name. Compare a known range with the direct `/availability` API and direct
MCP result.
Do not save prompt or response dumps containing Calendar data.
