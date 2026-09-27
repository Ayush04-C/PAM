# PAM Technical Design v0 1

## Purpose

This document explains the chosen technology stack, actual data flow, security policies, and the reasoning behind each choice for PAM v1. PAM is a private, self-hosted, single-user Google Calendar assistant. It is read-only and responds in text.

## Final v1 Stack

| Layer | Choice | Reason |
|---|---|---|
| Interface | Telegram Bot API | Simple personal interface for text and optional voice notes. Webhooks avoid polling costs. |
| Public edge | Nginx with HTTPS | One controlled public entry point, TLS termination, path routing, request limits, and reverse proxying. It matches Ayush's existing server pattern. |
| Backend | Python 3.12, FastAPI, Pydantic | Async webhooks and API calls, strict input validation, easy testing, and alignment with the existing personal-agent direction. |
| Agent runtime | Google ADK with a PAM policy layer | ADK can consume MCP tools. PAM's own harness keeps authorization and safety outside the model. |
| Calendar connection | Read-only Google Calendar MCP adaptor | Gives the agent one safe, structured Calendar capability rather than API credentials or unrestricted methods. |
| Model | BharatCode OpenAI-compatible Qwen endpoint | Reuses the provider already selected for Ayush's personal-agent work. It is used only to interpret flexible language. |
| Time calculation | Deterministic Python availability service | Correctly merges overlapping events and calculates busy time. This must not be left to an LLM. |
| Speech to text | Deepgram pre-recorded STT | Appropriate for complete Telegram voice-note files. No TTS is used. |
| Private state | MongoDB | Holds encrypted OAuth refresh tokens, settings, allowlist, and minimal redacted operational audit data. |
| Deployment | Docker Compose plus Nginx | A repeatable, low-overhead single-server deployment. Kubernetes, Redis, queues, and extra services are unnecessary in v1. |
| Tests | pytest with mocks | Tests policy and calculation logic without making model or Calendar calls. |

## Protocol Decisions

PAM v1 uses ordinary HTTPS request/response communication. It does not use WebSocket, HTTP streaming, or Server-Sent Events.

| Connection | Protocol | Why |
|---|---|---|
| Telegram to PAM | HTTPS webhook POST | Telegram sends an update only when Ayush messages the bot. No persistent connection is needed. |
| PAM to Telegram | HTTPS Bot API | PAM sends one final text reply. |
| PAM to Google Calendar | HTTPS REST, hidden behind MCP adaptor | Calendar reads are short, structured calls. |
| PAM to BharatCode | HTTPS chat-completions request | PAM needs one bounded intent-resolution request, not token-by-token streaming. |
| PAM to Deepgram | HTTPS pre-recorded STT request | Telegram voice notes are already completed files. |
| Containers | Docker private network | Nginx is the only public component. |

### Why no WebSocket or streaming

WebSockets are useful when a browser or desktop application continuously streams microphone audio. PAM v1 receives completed Telegram voice notes. Streaming would require persistent connections, reconnect handling, and extra state while offering no user benefit. HTTP streaming is also unnecessary because PAM must finish the deterministic Calendar calculation before returning the truthful final weekly result.

If a future desktop/mobile product supports a live microphone, it can use WebSocket STT. That is outside PAM v1.

## Nginx and HTTPS

Nginx is the public front door. It listens on ports 80 and 443, redirects HTTP to HTTPS, terminates TLS, and forwards only the Telegram webhook route to FastAPI.

Nginx was chosen because it is a mature reverse proxy and Ayush already uses an Nginx-based self-hosted deployment pattern. It handles HTTPS, reverse proxying, body-size limits, timeouts, and basic rate limits in one small component. Caddy or a managed load balancer could also work, but Nginx is the lowest-friction choice here.

### HTTPS setup policy

1. Point a PAM domain or subdomain to the server.
2. Obtain and auto-renew a TLS certificate.
3. Redirect all HTTP traffic to HTTPS.
4. Publicly accept only `POST /telegram/webhook`.
5. Use a small maximum body size for voice notes.
6. Verify Telegram's configured webhook secret inside FastAPI.
7. Never log secrets, tokens, or raw request content.

TLS protects traffic on the internet. The Telegram secret token prevents arbitrary callers from successfully using the webhook URL. Both are required.

## End-to-End Data Flow

### Typed message

1. Ayush sends `Show my next week` to Telegram.
2. Telegram sends an HTTPS webhook update to Nginx.
3. Nginx forwards it to FastAPI.
4. PAM validates the Telegram secret and Ayush's allowlisted Telegram user ID.
5. PAM either handles a known command directly or asks the model to resolve a date range.
6. The model may select only `get_weekly_availability`.
7. The Calendar MCP adaptor reads the exact validated interval from Google Calendar.
8. The availability service converts times to Asia/Kolkata, merges overlaps, and calculates busy time.
9. PAM formats every requested day with its hours and events, or `0 hours busy — Free day`.
10. PAM sends a text reply through Telegram and writes a redacted audit event.

### Voice note

1. Ayush sends a Telegram voice note.
2. PAM verifies the update and downloads the attachment temporarily.
3. Deepgram returns a transcript from the completed audio file.
4. The transcript enters the same typed-message flow at step 5.
5. PAM returns text only and deletes the temporary audio whether success or failure occurs.

## Agent and Harness Policy

Google ADK is the agent runtime, but it is not the authority. PAM's harness enforces all policy.

| Component | Allowed | Not allowed |
|---|---|---|
| Agent | Interpret flexible requests and choose the approved tool | Access OAuth tokens, invoke arbitrary tools, change Calendar, calculate busy hours |
| Harness | Validate identity, schemas, date range, tool limits, timeout, tokens, and audit policy | Trust model output as authorization |
| Availability service | Merge intervals, calculate time, format data | Make model calls or external writes |
| Calendar MCP adaptor | Refresh token and read structured events | Expose credentials or offer Calendar write methods |

The model receives the user's request and minimum structured intent context. Calendar event processing and final formatting happen locally. This reduces privacy exposure, cost, and hallucinations.

## Calendar Read and Write Policy

The agent has exactly one tool:

```text
get_weekly_availability(start_date, end_date, timezone)
```

- Read only after Ayush grants OAuth consent.
- Read only the primary calendar and only inside the validated requested range.
- Request a Calendar read-only OAuth scope. Never request a write scope in v1.
- Google Calendar remains the event source of truth. MongoDB never becomes a calendar copy.
- Recurring events are expanded before calculation.
- Use `Asia/Kolkata` for day boundaries and display.
- An all-day event displays as `All-day commitment`; it does not invent a 24-hour busy value. The day is not labelled `Free day`.
- PAM never creates, edits, moves, deletes, responds to, or shares events.

## Availability Service

The availability service is deterministic Python code. For each day it converts events to Asia/Kolkata, clips them to that day, sorts intervals, merges touching/overlapping intervals, and sums the merged duration.

For example, 10:00–11:00 plus 10:30–12:00 equals 2 hours busy, not 2.5. An event across midnight contributes only the part occurring on each day.

`Free day` is used only when there is no timed event and no all-day event. Otherwise PAM displays the actual busy duration plus the event list.

## Deepgram STT and Flux

Deepgram is the speech provider. Flux is Deepgram's live, streaming conversational speech-recognition model with turn detection. It is not the right tool for a completed Telegram voice note.

PAM v1 uses Deepgram's pre-recorded STT flow: upload the completed note, receive a transcript, answer in text, delete temporary audio. This is simpler and avoids a WebSocket session. PAM does not use TTS, generate audio, or retain audio files.

## BharatCode Model Policy

The BharatCode OpenAI-compatible Qwen endpoint interprets requests such as `What does my Monday look like?` It does not hold secrets, decide permissions, calculate time, or write data.

- One model call maximum per natural-language request.
- Fixed tool allowlist: only the Calendar availability tool.
- Hard timeout, token ceiling, and maximum one retry.
- Deterministic `/week` and `/nextweek` commands work even if the model is unavailable.
- On an unclear or failed natural-language request, PAM asks for clarification or returns a clear temporary error; it never invents calendar information.

## MongoDB Data Policy

| Collection | Content | Read | Write | Retention |
|---|---|---|---|---|
| `oauth_credentials` | Encrypted refresh token, expiry, scopes | Calendar adaptor only | OAuth callback and token refresh only | Until consent revocation or PAM removal |
| `user_config` | Telegram allowlist, timezone, settings | PAM only | Admin/bootstrap only | Until explicitly changed |
| `audit_events` | Timestamp, request ID, outcome, latency, result count, error class | PAM operator only | Append-only PAM service | 30 days initially |
| `rate_limits` | Minimal counters and windows | PAM only | PAM only | Auto-expire after the window |

Never store raw event descriptions, full audio, transcripts, OAuth client secrets, Telegram token, model key, or Deepgram key in audit records. Store service secrets in server environment configuration. Encrypt OAuth refresh tokens before they are stored in MongoDB. Client-side field encryption is a later hardening layer, not a replacement for server and backup security.

## Failure Policy

| Failure | PAM response |
|---|---|
| Invalid webhook secret or unknown Telegram user | Return no Calendar information. |
| OAuth revoked | Ask Ayush to reconnect Google Calendar. |
| Calendar unavailable | Say Calendar is temporarily unavailable; never invent a schedule. |
| STT failure | Ask for typed text or a shorter voice note. |
| Model unavailable | Serve deterministic commands; ask for a command when parsing is unavailable. |
| MongoDB unavailable | Fail closed; do not process Calendar credentials. |

## Deployment Policy

Docker Compose declares the PAM app and MongoDB on a private network. Nginx is the only public edge. It exposes ports 80/443; the app and database ports are not public. Secrets are injected as server environment configuration, excluded from Git, and rotated if exposed.

This is the smallest useful design: one public edge, one PAM application service, one database, one bounded read-only tool, and optional one-shot STT. Extra services must solve a proven need before they are added.
