# MCP integration

## Current architecture

PAM embeds a private shared Model Context Protocol server, launched as `python -m pam.mcp.server` for stdio clients. The current conversation CLI and Telegram composition instead use the MCP SDK with an injected server instance; their narrow Calendar client does not spawn a subprocess. The server constructs the Google or fake Calendar backend selected by PAM settings. With Drive enabled, it also registers the metadata tools described in [Stage 6](Driver/STAGE_06_MCP_TOOLS.md). It is not a public HTTP service.

## Exposed tool

The Calendar capability exposes `get_weekly_availability`. The shared server also exposes `drive_search_files` and `drive_get_file_metadata` when `PAM_DRIVE_ENABLED=true`. Stage 7's separate Drive conversation client offers those tools only after current owner/read/metadata-transfer/destination checks. This section describes the Calendar contract; see [Stage 7 routing](Driver/STAGE_07_ROUTING.md) for combined operation.

| Input | Required | Rules |
| --- | --- | --- |
| `start_date`, `end_date` | yes | ISO date strings; application range policy still applies. |
| `timezone` | yes | Valid IANA zone. PAM v1 display behavior is Asia/Kolkata. |
| `minimum_duration_minutes` | no | Integer 1–1440. |
| `requested_time` | no | `HH:MM`; only valid for a one-day range. |

The result is an object with `availability` (human-readable text) and `presentation` (deterministic facts). The latter is described in [AVAILABILITY_PRESENTATION.md](AVAILABILITY_PRESENTATION.md). The Pydantic MCP argument model forbids extra fields and turns invalid input into the generic tool error `invalid tool input`. Domain validation errors are also converted to a generic invalid-request error. Calendar failures become a generic reconnection/unavailability error.

## Client orchestration and restrictions

`ConversationService` discovers Calendar and, with matching current consent, the two Drive metadata tools. It validates names/arguments and preserves sequential call/result transcripts. Calendar retains its two-call limit; Drive-eligible turns have six total calls with at most two Calendar calls. Tool or MCP failure produces safe errors and, where available, verified partial results.

The MCP declaration marks the tools as read-only and non-destructive. No create, update, delete, authorization, download, shell, or generic network tools are offered. Drive adds only bounded filename search and metadata lookup. The separate Calendar client remains narrow; the owner-bound Drive client is explicitly composed alongside it.

## Error handling and timeouts

The MCP client maps transport/startup/protocol failures to `McpUnavailable`. `ConversationService` catches it and returns a generic Calendar retrieval message. Google-side failures are normalized deeper in the Calendar integration as described in [GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md).

The current MCP client does not define a separate application-level timeout setting. Do not document a timeout guarantee for it. The Supermemory SDK has its own configured timeout; it is unrelated to MCP transport.

## Test strategy

Offline tests cover the server tool schema, malformed input rejection, Calendar-unavailable mapping, output contract, model tool orchestration, tool allowlisting, and the no-tool path. They use fake readers, MCP clients, and scripted providers; live Google access is not required for the test suite.

## Current versus proposed

**Implemented:** one private shared Calendar/Drive MCP server, used through injected SDK or stdio clients, with direct terminal diagnostics. See [Stage 6 CLI instructions](Driver/STAGE_06_MCP_TOOLS.md#cli-calendar-conversation-and-direct-mcp-diagnostics).

**Not implemented:** a remote/public MCP deployment, cross-service discovery, multiple independently deployed servers, or write-capable tools. Those are future architecture work; see [ROADMAP.md](ROADMAP.md).
