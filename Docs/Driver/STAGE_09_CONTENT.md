# Stage 9: bounded content reading and cited summaries

Stage 9 adds `drive_get_file_content(file_id)` to the existing shared MCP server.
It reuses the Drive authorization/reader, narrow client, file references, provider
transcripts and conversation/memory boundaries. Content is disabled by default.
No new server, dependency, memory backend or file index is introduced.

## Formats, limits and data flow

| Format | Content behavior |
| --- | --- |
| Native Google Docs | Drive `files.export`, requested as `text/plain` |
| Uploaded `text/plain` | Drive `files.get` with `alt=media`; strict UTF-8 with optional BOM |
| Other formats, folders, shortcuts and shared-drive files | Unsupported for content; existing metadata policy remains unchanged |

Each read verifies current metadata, file identity, MIME, trash/shared-drive state
and `capabilities.canDownload`. Uploaded text also needs valid size metadata.
It never follows shortcuts, arbitrary URLs, export links or redirects, and never
bypasses download restrictions. All requests use fixed Google API endpoints.
See Google's [download/export guide](https://developers.google.com/workspace/drive/api/guides/manage-downloads).

Downloads stream with a 256 KiB cap checked before buffer growth. Extracted text
has a 12,000-character cap; oversized content is rejected, not silently truncated.
Invalid UTF-8, NUL/binary or empty text is rejected. Other unsafe display controls
are removed. Text is split into at most 12 numbered passages of 1,000 characters.
No raw document is saved to disk or the session reference store.

The existing 20,000-character Drive context ceiling includes references and
cumulative serialized arguments/results. Six total calls and two Calendar calls
remain the conversation limits. HTTP socket timeouts are 20 seconds and streaming
checks elapsed time between chunks. These are not a hard whole-workflow deadline
or a model token-limit guarantee. Provider failures remain safe errors.

The MCP result carries `source=google_drive`, `data_kind=content`, `untrusted=true`,
verified file metadata, passages, `complete=true` and an optional safe error.
The narrow client validates IDs, canonical URLs, supported MIME, passage labels,
lengths/control policy, completeness, error flags and unknown fields.

Content answers use citations such as `[file-id:P1]`. The host checks them against
this turn's successful content results, rejects unknown/missing passage citations
and unverified URLs, and appends canonical source links. This validates citation
identity, not semantic accuracy. Passages are text offsets, not PDF pages or
document sections. The modification timestamp is from preflight metadata; a
concurrent edit is not a transactional snapshot guarantee.

## Consent, scope compatibility and memory

`PAM_DRIVE_CONTENT_ENABLED=false` is the default. Setting it true registers the
content tool, but does not authorize reads or model transfer by itself.

Google content access requires the read-only scope
`https://www.googleapis.com/auth/drive.readonly`. Existing metadata-only grants
still load and support metadata. Content-enabled authorization requests the
content scope and accepts only the known read-only profile (including Google's
aggregation with the existing metadata scope), never additional/write scopes.
A scope upgrade cannot reuse an unproven old refresh token; failed upgrades
preserve the saved grant. A successful reconnect resets transfer permissions.
See Google's [scope documentation](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

The existing operator `/permissions` endpoint now accepts an optional strict
boolean `allow_content_transfer`, default false. Enabling it requires read access,
metadata-transfer permission, the content feature/scope and explicit confirmation
of the configured model destination. `/status` reports the effective permission.

The conversation exposes/invokes content only with current matching consent.
File IDs must come from verified references/results or the current user's explicit
ID/recognized Google link. Permissions are rechecked before sensitive delivery
and before committing/returning an answer. Content-derived history retains a
content marker, so later metadata-only consent cannot authorize that history.
`/new` clears temporary context; changed scope/credentials invalidate references.

Raw passages stay in the current tool transcript. Only the assistant answer,
which may include quotes, enters bounded-by-message-count transient history with
its content marker. The existing shared Supermemory backend is reused, with
automatic recall/ingestion suppressed for sensitive turns and follow-ups.
Contextual Remember cannot import documents or summaries; explicit literal
user-written preferences retain existing behavior. No automatic document sync.

## Later manual setup and CLI acceptance

No live Google/model acceptance was performed during implementation. Use these
steps when ready to approve a non-sensitive test document for your configured
provider. Do not edit encrypted credential files or rotate Calendar's key.

1. In Google Cloud Console, select the existing PAM project and open **Google
   Auth Platform → Data access → Add or remove scopes**. Add
   `https://www.googleapis.com/auth/drive.readonly` and save. The already-enabled
   Drive API and existing dedicated Drive OAuth web client are reused; no Docs
   API or new project is needed. Restricted-scope release requirements remain a
   Stage 10 review item.
2. In your ignored `.env`, set `PAM_DRIVE_CONTENT_ENABLED=true` and retain
   `PAM_DRIVE_ENABLED=true`. Restart provisioning/CLI processes to load settings.
3. Start the existing local provisioning API in terminal 1:

   ```powershell
   .venv\Scripts\python.exe -m uvicorn pam.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
   ```

4. In terminal 2, reauthorize Drive using the updated scope:

   ```powershell
   $ErrorActionPreference = 'Stop'
   $pamSecureSecret = Read-Host 'PAM_APP_SECRET' -AsSecureString
   $pamHeaders = @{ Authorization = 'Bearer ' + [System.Net.NetworkCredential]::new('', $pamSecureSecret).Password }
   $pamBase = 'http://127.0.0.1:8000/oauth/google/drive'
   $pamStart = Invoke-RestMethod -Method Post -Uri "$pamBase/start" -Headers $pamHeaders
   Start-Process $pamStart.authorization_url
   ```

   Complete Google consent with the configured account. The callback's connected
   status does not grant model transfer. A failed upgrade leaves the old grant.
5. Review the exact destination, then enable content transfer **only if approved**:

   ```powershell
   $pamStatus = Invoke-RestMethod -Uri "$pamBase/status" -Headers $pamHeaders
   $pamStatus
   $pamPermission = @{
       allow_read = $true
       allow_metadata_transfer = $true
       allow_content_transfer = $true
       confirmed_destination = $pamStatus.model_destination
   } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri "$pamBase/permissions" -Headers $pamHeaders -ContentType 'application/json' -Body $pamPermission
   ```

6. Start CLI and use a supported, non-sensitive test file:

   ```powershell
   .venv\Scripts\python.exe -m pam.conversation.cli
   ```

   ```text
   /help
   Find PAM TEST and summarize its contents with source passages.
   Summarize file 1 and check my Calendar availability tomorrow.
   /new
   ```

The existing BharatCode/Gemini provider handles generation; no new model client is
needed. Telegram uses the same service, but a CLI grant still does not authorize
another Telegram owner. Test your owner mapping separately in Stage 10.

To withdraw content transfer, POST permissions with `allow_content_transfer=false`.
To disable the capability, set the content feature false and restart. Sensitive
history then needs `/new`. This does not revoke Google's broader OAuth grant;
Google revocation and code rollback are separate operations.

## Errors, tests and checkpoint

Fixed safe error categories cover unsupported type, denied download, oversized
content, invalid/empty encoding, invalid response, missing consent, reconnect,
rate limit and temporary failure. Details and source bodies are not logged.
All-failed content reads cannot produce a claimed summary. Invalid citations stop
before committing the answer. Existing verified Calendar fallback remains intact.

74 new cases in `pam/tests/test_drive_content.py` and
`pam/tests/test_drive_content_routing.py` cover formats, scope upgrades, operator
permissions, streaming stop/close, encoding/controls, revocation, strict MCP
payloads, references, context limits, citations, injection, memory follow-ups,
both provider serializers and real-reader/MCP/scripted-model composition.

All 525 offline tests pass. Ruff lint/format, strict mypy, links and Git whitespace
checks pass. No real Google, model, Telegram or Supermemory acceptance was run;
no local `.env`, credentials, scopes or saved permissions were changed.
Stage 10 remains live acceptance, operational measurements and rollout/rollback.
