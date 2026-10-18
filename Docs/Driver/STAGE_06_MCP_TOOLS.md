# Stage 6: shared Calendar and Drive MCP tools

The existing `pam/mcp/server.py` now builds one private server named `PAM`.
Calendar keeps `get_weekly_availability` and its existing schema/result. When
`PAM_DRIVE_ENABLED=true`, `pam/mcp/driver.py` adds two metadata-only tools using
the Stage 5 reader. Registration and discovery do not read credentials or call
Google. A missing grant fails only when a Drive operation is requested.

## Implementation and boundary

| Tool | Arguments | Operation |
| --- | --- | --- |
| `get_weekly_availability` | Existing Calendar arguments | Existing selected Calendar backend |
| `drive_search_files` | Optional `name`, `page_size=10`, `page_token` | One page of filename search or metadata listing |
| `drive_get_file_metadata` | Required `file_id` | One metadata record |

Drive schemas forbid unknown fields and enforce strict types and Stage 5 limits:
200-character nonblank search, page size 1–50, 4096-character printable opaque
cursor, and 256-character ASCII file ID. Strings such as `"null"` remain literal
searches/cursors; Drive disables SDK JSON-string coercion. No owner, credential,
scope, endpoint, raw query, content or write arguments exist.

`SafeToolArguments` reuses Calendar's existing safe validation behavior. Calendar
tool construction is reusable by both the shared server and its unchanged
standalone test factory. The reader exposes its configured owner for trusted
composition; every Drive invocation uses that identity and reloads current consent
before network I/O. The MCP adapter imports no model providers, Telegram, or memory
services. Google request limits, response validation and refresh remain in the
existing adapter rather than being reimplemented in the tools.

This is a private **single-owner** server. Local SDK clients and stdio processes
must run under the trusted operator account. There is no public MCP HTTP endpoint
or per-client authentication added here. Do not expose the server to untrusted
users or wire arbitrary Telegram users to this owner. Authenticated transport
mapping and model-transfer enforcement belong to later conversation integration.
Read consent can be withdrawn through Stage 4 provisioning; the next MCP read
observes it. Withdrawal does not cancel a Google request already in flight.

The conversation client still exposes only Calendar to the model. Registering
Drive does not authorize model transfer, and it does not enable natural-language
Drive requests in the conversation CLI yet. MCP annotations and provenance labels
are information for trusted callers, not a security sandbox for external clients.

## Structured output and errors

Drive success and runtime failure results use this envelope:

```json
{
  "source": "google_drive",
  "data_kind": "metadata",
  "untrusted": true,
  "files": [],
  "next_page_token": null,
  "incomplete_search": false,
  "error": null
}
```

Successful file records contain `file_id`, `name`, `mime_type`, optional
`modified_time`, and `source_url`. A metadata lookup returns a one-element files
array. Search preserves empty/partial pages and continuation tokens; it does not
auto-scan the Drive. Metadata is also present in the MCP text representation, so
any later host must gate both representations before forwarding to a model.

Runtime failure sets MCP `is_error=true`, returns no files, and fills `error`
with `code`, fixed `message`, and `retryable`. Stage 5's consent/reconnect,
unavailable-file, pagination, rate-limit, temporary-failure and invalid-response
codes are preserved. Unexpected exceptions produce a generic temporary failure;
their raw messages are not forwarded or logged by this adapter.

Argument validation uses the standard MCP tool-error channel with the fixed
message `invalid tool input`, before reader execution; it does not use the runtime
error envelope. Calendar retains its existing error behavior and output contract.
An API failure in one tool family does not block the other family. Invalid global
settings still fail startup; that is distinct from an individual API outage.

## CLI: Calendar conversation and direct MCP diagnostics

From PowerShell in `D:\Learning\PAM`, use the virtual environment's Python.

### Calendar through natural-language conversation

This already existed before Stage 6:

```powershell
.venv\Scripts\python.exe -m pam.conversation.cli
```

At `PAM >`, enter, for example:

```text
Show my Calendar availability for 19–25 October 2026 in Asia/Kolkata.
```

This mode requires the configured BharatCode/Gemini provider and its API key.
Calendar uses the selected `PAM_CALENDAR_BACKEND`: `fake` means fixture data and
`google` means your authorized Calendar. `/status`, `/new`, and `exit` remain
available. Drive natural-language routing is not added by this stage.

### List the shared server's tools without a model or Google call

```powershell
.venv\Scripts\python.exe -m pam.mcp.server --list-tools
```

With Drive enabled, expected names are `get_weekly_availability`,
`drive_search_files`, and `drive_get_file_metadata`. With Drive disabled, only
Calendar is registered. Settings validation still applies to selected backends.

### Search Drive directly through MCP

```powershell
'{"name":"PAM TEST"}' | .venv\Scripts\python.exe -m pam.mcp.server --call-tool drive_search_files
```

These direct diagnostics use the MCP SDK against the same server composition;
they do not create a model or Supermemory client. Actual Drive calls require the
Stage 4 grant and read consent. The result prints metadata to your terminal.

To select the known test file and fetch its metadata by ID:

```powershell
$pamSearchResult = '{"name":"PAM TEST"}' | .venv\Scripts\python.exe -m pam.mcp.server --call-tool drive_search_files | ConvertFrom-Json
$pamTestMatches = @($pamSearchResult.files | Where-Object { $_.name -eq 'PAM TEST.txt' })
if ($pamTestMatches.Count -ne 1) { throw 'Expected one PAM TEST.txt match' }
@{ file_id = $pamTestMatches[0].file_id } | ConvertTo-Json -Compress | .venv\Scripts\python.exe -m pam.mcp.server --call-tool drive_get_file_metadata
```

To invoke Calendar directly without an LLM:

```powershell
'{"start_date":"2026-10-19","end_date":"2026-10-25","timezone":"Asia/Kolkata"}' | .venv\Scripts\python.exe -m pam.mcp.server --call-tool get_weekly_availability
```

`--call-tool` accepts one JSON object from stdin, capped at 8192 characters. It
prints JSON and exits 0 on success, 1 for tool/transport failure, or 2 for invalid
diagnostic input/configuration. Raw invalid input and settings values are not
printed. JSON output uses escaped Unicode for Windows terminal compatibility.
Do not run diagnostics on a stdio stream already in use by another MCP client.

Without diagnostic flags, `python -m pam.mcp.server` still runs the normal stdio
server and waits for an MCP client; it is not an interactive chat prompt.
Conversation `/status` now reports Drive's direct-MCP availability instead of the
old Stage 3 text saying Drive tools were unimplemented.

## Tests and verification

`pam/tests/test_mcp_drive.py` adds 40 cases covering discovery, read-only annotations,
input/output schemas, unknown fields, strict types, bounds, literal `null`, fixed
owner binding, result provenance, pagination, every runtime error code, unexpected
failure redaction, independent Calendar/Drive failures, Calendar-only conversation
discovery, offline registration, real-reader consent withdrawal, subprocess stdio
discovery/missing grant, CLI commands, malformed/oversized/deep JSON and sanitized
startup errors. Existing CLI and Calendar stdio tests were updated for the shared
server's configuration-dependent registration; the Calendar-only test explicitly
disables Drive so it cannot depend on a developer's local `.env`.

Validation: all 360 tests pass; Ruff lint/format, strict mypy, documentation links
and Git whitespace checks pass. Automated tests use fake data. Separate live
terminal checks discovered all three tools, searched `PAM TEST.txt`, and fetched
its metadata by returned ID through MCP. No content, model call or memory write
was involved. Calendar compatibility passed the offline regressions; no new live
Calendar or hosted-model conversation was performed as part of this verification.

Next: Stage 7 adds validated assistant routing and transcript handling. That is
where natural-language Drive requests and combined Calendar/Drive tool use will
begin, with transfer consent enforced before model exposure.
