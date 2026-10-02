# Local BharatCode provider

Phase 7.5 makes BharatCode the documented active hosted-provider configuration
while retaining Gemini as an explicitly selected legacy provider. The safe code
fallback remains `fake`, so imports and offline CI never require a hosted key.
The provider remains behind PAM's existing `ModelProvider` interface:

```text
CLI or Telegram -> ConversationService -> BharatCodeProvider -> local Calendar MCP
```

PAM uses BharatCode's OpenAI-compatible base URL:

```text
https://bharatcode.ai/api/model/v1
```

The provider uses stateless `/chat/completions` requests. PAM owns system
instructions, current Asia/Kolkata time, the user message, tool-call loop, and
tool-result messages. It does not use hosted tools, provider-side memory, or
stored conversations.

## Configuration and discovery

Put these values only in ignored `.env`:

```dotenv
PAM_MODEL_PROVIDER=bharatcode
PAM_BHARATCODE_API_KEY=your-key
PAM_BHARATCODE_BASE_URL=https://bharatcode.ai/api/model/v1
PAM_BHARATCODE_MODEL=deepseek-v4.1-flash
```

List the current account catalog without printing the key or request headers:

```powershell
.\.venv\Scripts\python.exe -m pam.conversation.bharatcode_models
```

At implementation time, the live catalog listed `qwen-3.8-27b` and
`deepseek-v4.1-flash`. The latter is the configured default because BharatCode
documents it for tool use. The catalog is authoritative; override the model if
your account changes.

## Tool calling and safety

`BharatCodeProvider` converts only the existing MCP-discovered tool schema to
OpenAI-compatible function declarations. The model can request only the
already-allowlisted `get_weekly_availability` capability. PAM sends MCP output
back as a `tool` message with the provider tool-call ID and limits each turn to
two tool rounds.

BharatCode does not receive OAuth tokens, Google client secrets, encrypted
credentials, the credential encryption key, Telegram bot token, Gemini key, or
its own API key. MCP remains the local execution boundary; neither BharatCode
nor Telegram calls Google Calendar directly.

The OpenAI client uses one bounded SDK retry and maps authentication, invalid
model, timeout, connection, capacity, and malformed-response errors to the
existing safe `ModelUnavailable` boundary. It does not auto-fallback to Gemini.

## Manual checks

Run the normal CLI after configuring BharatCode:

```powershell
.\.venv\Scripts\python.exe -m pam.conversation.cli
```

Then run the unchanged Telegram bot:

```powershell
.\.venv\Scripts\python.exe -m pam.telegram.bot
```

Confirm a non-Calendar response, a Calendar tool call, a multi-day request, and
a delete request that remains read-only. To return to Gemini intentionally,
set `PAM_MODEL_PROVIDER=gemini` and configure only the matching Gemini settings.
