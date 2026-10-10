# MCP integration

## Current architecture

PAM embeds a private local Model Context Protocol server, launched as `python -m pam.mcp.server`. `CalendarMcpClient` starts that process using standard input/output transport. The conversation factory uses this local launch configuration; the MCP server constructs the same Google or fake availability backend selected by PAM settings. It is not a public HTTP service and it does not expose arbitrary Google Calendar capabilities.

## Exposed tool

The server exposes exactly one structured, read-only tool: `get_weekly_availability`.

| Input | Required | Rules |
| --- | --- | --- |
| `start_date`, `end_date` | yes | ISO date strings; application range policy still applies. |
| `timezone` | yes | Valid IANA zone. PAM v1 display behavior is Asia/Kolkata. |
| `minimum_duration_minutes` | no | Integer 1–1440. |
| `requested_time` | no | `HH:MM`; only valid for a one-day range. |

The result is an object with `availability` (human-readable text) and `presentation` (deterministic facts). The latter is described in [AVAILABILITY_PRESENTATION.md](AVAILABILITY_PRESENTATION.md). The Pydantic MCP argument model forbids extra fields and turns invalid input into the generic tool error `invalid tool input`. Domain validation errors are also converted to a generic invalid-request error. Calendar failures become a generic reconnection/unavailability error.

## Client orchestration and restrictions

`ConversationService` discovers available tools for the model turn. A model tool request is accepted only when its name is exactly `get_weekly_availability`; every other name receives the read-only refusal. The loop allows at most two tool rounds. Tool or MCP failure produces a safe assistant-facing failure rather than an internal exception.

The MCP declaration marks the tool as read-only and non-destructive. No create, update, delete, authorization, shell, file, or generic network tools are offered. This is enforced independently by the server schema and the conversation allowlist.

## Error handling and timeouts

The MCP client maps transport/startup/protocol failures to `McpUnavailable`. `ConversationService` catches it and returns a generic Calendar retrieval message. Google-side failures are normalized deeper in the Calendar integration as described in [GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md).

The current MCP client does not define a separate application-level timeout setting. Do not document a timeout guarantee for it. The Supermemory SDK has its own configured timeout; it is unrelated to MCP transport.

## Test strategy

Offline tests cover the server tool schema, malformed input rejection, Calendar-unavailable mapping, output contract, model tool orchestration, tool allowlisting, and the no-tool path. They use fake readers, MCP clients, and scripted providers; live Google access is not required for the test suite.

## Current versus proposed

**Implemented:** one private stdio Calendar MCP server and one read-only availability tool, used internally by PAM.

**Not implemented:** a remote/public MCP deployment, cross-service discovery, multiple independently deployed servers, or write-capable tools. Those are future architecture work; see [ROADMAP.md](ROADMAP.md).
