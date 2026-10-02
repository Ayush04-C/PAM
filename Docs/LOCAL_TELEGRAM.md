# Local Telegram text bot

Phase 7 connects Telegram private text messages to the existing
`ConversationService`. It uses long polling locally; no public webhook, tunnel,
Nginx, or deployment infrastructure is required.

```text
Telegram private chat -> TelegramAdapter -> ConversationService -> Gemini -> Calendar MCP
```

The adapter is transport-only. It never calls Google Calendar, MCP tools,
Gemini SDK APIs, OAuth, or credential storage directly.

## Create and configure a bot

1. In Telegram, open the official **BotFather** account.
2. Send `/newbot`, choose a display name, then choose a valid bot username.
3. Copy the generated token and save it only in the ignored local `.env`.
4. Find your numeric Telegram user ID. A safe method is to send `/start` to a
   reputable ID-display bot, then remove it; never use a username as PAM
   authorization.
5. Add only your numeric ID to `PAM_TELEGRAM_ALLOWED_USER_IDS`.

Example local-only configuration:

```dotenv
PAM_TELEGRAM_ENABLED=true
PAM_TELEGRAM_BOT_TOKEN=your-token
PAM_TELEGRAM_ALLOWED_USER_IDS=123456789
PAM_MODEL_PROVIDER=gemini
PAM_GEMINI_API_KEY=your-gemini-key
PAM_CALENDAR_BACKEND=google
```

The enabled bot fails closed if its token or numeric user-ID allowlist is
missing. It accepts only one-to-one private chats. Unauthorized, group, channel,
and malformed updates never reach `ConversationService`.

## Run

```powershell
.\.venv\Scripts\python.exe -m pam.telegram.bot
```

Open the bot and send `/start`, `/help`, `/new`, or a text question such as
`How busy am I today?`. `/start` and `/help` are static responses and do not
call a provider or Calendar MCP. `/new` clears only the authorized private
chat's in-memory context without calling a provider or MCP. Other authorized
text reaches the same bounded multi-turn `ConversationService` used by the
local CLI.

Only text is supported in Phase 7. Media receives a short text-only response.
Incoming text is limited to 4,096 characters. Longer plain-text answers are
split safely at whitespace boundaries, using Telegram's 4,096-character
`sendMessage` limit.

## Privacy and manual check

The bot token, Gemini key, OAuth tokens, credential encryption key, and Calendar
credentials are never sent to Gemini, MCP, Telegram replies, or logs. PAM does
not log full Telegram text or Calendar output. Set
`PAM_CONVERSATION_DEBUG_TOOL_CALLS=true` only when needed; it logs the invoked
tool name, not its arguments or result.

Before treating the bot as ready, verify `/start`, `/help`, an availability
question, a multi-day question, and a delete request (which must remain
read-only). Also verify an unauthorized account and a group cannot trigger a
Calendar query. Do not enable BotFather payments, inline mode, administration,
location, or other unrelated capabilities.
