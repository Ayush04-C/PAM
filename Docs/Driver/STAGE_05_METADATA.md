# Stage 5: bounded Drive search and metadata

Stage 5 adds `GoogleDriveReader` in `pam/integrations/google_drive.py`, using the
existing owner-bound authorization and encrypted grant. The shared Google wiring
now constructs that authorization for both HTTP provisioning and local reads.
There are no new settings, Google scopes, dependencies, MCP tools, model calls,
memory writes or content downloads. Google Drive API remains the upstream service.

## Operations and limits

| Method | Inputs | Output |
| --- | --- | --- |
| `search(owner, name=None, page_size=10, page_token=None)` | Authenticated owner; optional filename search and continuation | One `DrivePage` of metadata, optional next token, incomplete-search flag |
| `get_metadata(owner, file_id)` | Authenticated owner and validated file ID | One `DriveFile` |

`DriveFile` contains ID, name, MIME type, optional timezone-aware modification
time and a Google Drive source URL constructed from the validated ID. Folder
URLs use the folder path. API-supplied arbitrary links are not forwarded or fetched.
Records remain untrusted data: filenames cannot grant consent or execute tools.
Private names, IDs, source URLs, file collections and cursors are excluded from
their default object representations. This does not prevent a caller explicitly
printing or serializing those fields; future orchestration must preserve provenance.

Limits are application limits, not Google's advertised maximums:

- Page size defaults to 10 and must be an integer from 1 through 50.
- Optional filename text must be nonblank, at most 200 characters, and contain
  no ASCII control characters. Quotes and backslashes are escaped in the query.
- IDs contain only ASCII letters, digits, hyphens and underscores, up to 256
  characters. URLs, paths and caller-supplied Google expressions are rejected.
- Opaque page tokens are 1–4096 printable, non-space ASCII characters. Continue
  with the same search and page-size parameters. They are not authorization or
  session-bound references; conversational cursor binding belongs to a later stage.
- Each operation requests one page/file. Empty pages can still carry a next token;
  callers must not treat a first page as an exhaustive inventory.
- Responses are streamed and capped at 128 KiB after decompression. The response
  is closed on success or failure. Large names/results can exceed this cap even
  within the page-count limit; the adapter rejects rather than silently truncates.
- Google requests and refresh calls use 20-second transport timeouts. These are
  request timeouts, not a total workflow deadline. There is no application retry
  loop, automatic pagination, or HTTP redirect following.

Search uses `name contains`, which follows Google's filename prefix-match
semantics, not a full-text or arbitrary substring search. It is restricted to
the user corpus and Drive space, excludes trash, and sorts by modification time
then name. Shared-drive support is disabled. A returned shared-drive or trashed
record is rejected as unavailable; shortcut records are returned as metadata
without following their target. Files shared directly with the account can appear
in the user corpus; this is not an owner-only inventory filter.

Fields requested: `id`, `name`, `mimeType`, `modifiedTime`, `trashed`, `driveId`,
plus list pagination/completeness fields. No descriptions, file content,
permissions, download URLs or full resource payloads are requested.

API contracts: [files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list),
[files.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get),
and [search syntax](https://developers.google.com/workspace/drive/api/guides/search-files).

## Consent, refresh and errors

Inputs are validated first. Each read then checks the owner, reloads the encrypted
grant, verifies its configured client/account/scopes, and requires current read
consent before refreshing credentials or calling Drive. The same scoped refresh
helper serves Stage 4's connection check. Credentials are not cached between
operations, and a changed grant or withdrawn consent is observed on the next read.
Revocation does not cancel a network request already in flight.

Read consent does not grant model transfer or memory retention. Existing Stage 2
rules still apply when later stages deliver these results to conversation code.
This stage does not wire retrieved data into that conversation path.

`DriveReadError` exposes a fixed `code`, safe message and `retryable` flag:

| Code | Meaning |
| --- | --- |
| `invalid_request` | Invalid input or rejected initial request |
| `consent_required` | Wrong owner or read consent withdrawn |
| `reconnect_required` | Missing/invalid grant, revoked credential, changed scopes or HTTP 401 |
| `unavailable` | HTTP 403/404/410, trash or unsupported shared-drive record |
| `invalid_page_token` | Google rejects a continuation request; restart the search |
| `rate_limited` | HTTP 429 or recognized Google quota/rate-limit reason; retry later |
| `temporary_failure` | Network/refresh/server failure or unexpected redirect; retry later |
| `invalid_response` | Invalid JSON, malformed metadata, ID mismatch or exceeded bound |

Only rate-limited and temporary-failure errors are retryable. File absence and
access denial share an unavailable result. Error messages never include raw
responses, tokens, private filenames or queries. The adapter does not log payloads.

## Reproduce the local metadata check

After Stage 4 authorization, use PowerShell in the repository root. This explicitly
queries Google for the designated test filename and prints only its metadata:

```powershell
@'
from pam.config import Settings
from pam.integrations.google_wiring import create_drive_authorization
from pam.integrations.google_drive import GoogleDriveReader, DriveReadError

try:
    auth = create_drive_authorization(Settings())
    reader = GoogleDriveReader(auth)
    page = reader.search(auth.owner, name="PAM TEST", page_size=10)
    matches = [item for item in page.files if item.name == "PAM TEST.txt"]
    if len(matches) != 1:
        print("Expected one PAM TEST.txt match on this page; check filename or pagination.")
    else:
        item = reader.get_metadata(auth.owner, matches[0].file_id)
        print(item.name, item.mime_type, item.modified_time)
except DriveReadError as error:
    print(error.code, str(error))
except Exception:
    print("Local configuration check failed; review settings without printing secrets.")
'@ | .venv\Scripts\python.exe -
```

The local script deliberately uses the configured operator's owner. Future remote
adapters must obtain owner identity from authenticated host context rather than
accepting the model's claim about an owner.

Live acceptance: the user-designated `PAM TEST` was found as `PAM TEST.txt`.
Search and lookup by returned ID succeeded, reporting `text/plain` with modification
time present. No content was downloaded, no credential files were changed, and
no model or Supermemory call was made. Other Drive files were not enumerated.

## Verification and handoff

Tests in `pam/tests/test_drive_metadata.py` cover input bounds, escaped searches,
exact fields/parameters, current-consent enforcement before network I/O, owner and
grant mismatch, empty/partial pages, folders/shortcuts, malformed metadata,
response-size limits, resource closure, HTTP errors, refresh failures and timeouts.
Stage 4 OAuth and existing Calendar/conversation/memory tests remain regression gates.

Validation: 320 tests pass (61 new Stage 5 cases), with fake Google services in
the automated suite. Lint, formatting, strict mypy, documentation links and Git
whitespace checks pass. The separate live metadata check above also passed.
Existing Calendar behavior was checked by the regression suite; a new live
Calendar availability request was not performed in this stage.

Next is Stage 6: expose validated metadata operations in `pam/mcp/driver.py`
through the existing shared server. Assistant routing, authenticated transport
owner mapping, cursor/reference binding and model-transfer enforcement remain
later integration work.
