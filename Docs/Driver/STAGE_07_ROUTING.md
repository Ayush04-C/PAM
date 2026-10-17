# Stage 7: Calendar and Drive assistant routing

Stage 7 connects the metadata MCP tools to the existing conversation service.
There is one shared server and two narrow clients: the existing Calendar client
and a new owner-bound Drive client. No new server, OAuth scope, dependency,
content tool, memory backend or environment variable is introduced.

## Implementation

- `ConversationService` offers Calendar as before. It additionally offers the
  two Drive tools only when their discovery succeeds and current owner/read/
  metadata-transfer/destination checks pass. The model chooses among the offered
  capabilities; the host validates every tool name and Drive argument.
- CLI and Telegram composition share `local_drive_support`. It creates an optional
  Drive client and supplies a loader for the saved grant's current permissions.
  All Drive calls bind to the configured operator owner. The default `cli-local`
  owner matches the CLI; Telegram does not automatically inherit that identity.
- Both BharatCode and Gemini serialize the full ordered call/result transcript,
  including earlier exchanges before the latest result. Parallel tool calls are
  rejected, and duplicate nonempty call IDs cannot execute twice.
- Calendar-only requests retain the existing two-call ceiling and legacy failure
  behavior. Drive-eligible turns allow up to six total calls, with at most two
  Calendar calls. Failed/invalid attempts consume the same finite turn budget.
- The Drive context character limit counts supplied Drive context plus cumulative
  serialized Drive arguments/results in the current turn. Oversized results fail
  before model delivery. It is not a provider-token limit or a total workflow
  timeout; bounded message history and existing transport timeouts also apply.
- Metadata lookup requires an ID from this turn's verified results or an exact
  ID token supplied in the current user message. Cursors must come from a prior
  same-query/same-page-size search in the current turn. A persistent cross-turn
  file/cursor reference store and richer selection UI belong to Stage 8.
- The Drive client validates result schemas, source/data-kind/untrusted labels,
  IDs, canonical Google source links, page counts/cursors and MCP error flags.
  It replaces error messages with known safe messages rather than trusting raw
  strings. It ignores unknown tool names and uses host-owned argument schemas.

## Consent and memory boundary

Read permission alone is insufficient. The current grant must authorize metadata
transfer to the provider's exact destination identity. A trusted loader takes
precedence over any supplied internal consent value. Configuration/model changes,
wrong owners, missing grants and withdrawn permissions cannot silently fall back.

Consent is reloaded before Drive exposure/calls, before model requests containing
sensitive context/results, and before returning/committing a sensitive answer.
Revocation cannot retract requests already sent, but it blocks subsequent delivery
and retained derived output. Calendar can still operate for owners without Drive
permission. Retrieved text never grants tools, consent or memory actions.

Successful Drive-derived answers keep the existing history provenance marker;
follow-ups recheck it even after older history entries are trimmed. Raw tool
transcripts are ephemeral and are not committed as conversation history. `/new`
clears transient history/markers, not OAuth or durable memories.

Automatic Supermemory recall and ingestion are conservatively skipped on turns
where Drive tools are offered, even if the model chooses only Calendar or gives
a plain answer. They also remain disabled for retained sensitive history. This
reduces passive memory for a Drive-authorized owner; Stage 8 may refine it with
proved provenance rules. Explicit user-written Remember/Forget behavior remains
as in Stage 2; the model cannot invoke memory tools. No separate memory service
is created and no Drive data is automatically stored there.

This is still single-owner Drive provisioning. Telegram's authenticated memory
owner must match the saved configured Drive owner to receive Drive tools. A CLI
grant does not authorize other Telegram users; broader onboarding/owner mapping
is not implemented here. Arbitrary user-pasted text is not automatically labeled
as retrieved Drive data, as documented in Stage 2.

## Error handling

| Situation | Behavior |
| --- | --- |
| No current Drive transfer permission | Drive tools omitted; hallucinated Drive calls denied without a Drive invocation |
| Retained sensitive history no longer authorized | Stop before forwarding history or making automatic memory calls |
| Invalid arguments, invented file ID or unrelated cursor | Reject safely; no Google metadata request for invalid references |
| Unknown/content/write/memory tool | Refuse; no arbitrary dispatch |
| Invalid MCP envelope/source/link/error flag | Reject through the narrow client; never forward raw payload |
| Drive request fails | Supply a fixed metadata error for a possible partial answer |
| Calendar fails in a combined turn | Supply a fixed Calendar failure so a healthy Drive result can still be used |
| Model failure or budget exhaustion in combined mode | Preserve an already verified Calendar availability answer when available; state the failure |
| Context too large or consent revoked | Stop before the next sensitive model request |

Failed turns are not committed as new history, and raw SDK errors are not shown.
Calendar output/presentation rules remain unchanged. Prompts and labels identify
untrusted data; the code's allowlists, owner/consent checks and budgets enforce
authority. This is not a claim of complete prompt-injection resistance.

## CLI setup and verification

Your current local grant was checked without network calls: read=true,
metadata-transfer=false, content-transfer=false. Those permissions were preserved.
No live Drive metadata was sent to BharatCode/Gemini during implementation.

Calendar conversation and direct MCP diagnostics still work as before. To enable
Drive in a hosted-model conversation, review and explicitly grant metadata transfer
using the existing operator-authenticated provisioning endpoint:

1. Confirm `PAM_DRIVE_ENABLED=true`, the configured model is correct, and
   `PAM_DRIVE_OWNER_ID` matches `PAM_MEMORY_CLI_OWNER_ID` (`cli-local` by default).
   Preserve existing credentials and encryption key.
2. In terminal 1, start local provisioning:

   ```powershell
   .venv\Scripts\python.exe -m uvicorn pam.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
   ```

3. In terminal 2, enter the operator secret privately and review the destination:

   ```powershell
   $pamSecureSecret = Read-Host 'PAM_APP_SECRET' -AsSecureString
   $pamHeaders = @{ Authorization = 'Bearer ' + [System.Net.NetworkCredential]::new('', $pamSecureSecret).Password }
   $pamBase = 'http://127.0.0.1:8000/oauth/google/drive'
   $pamStatus = Invoke-RestMethod -Uri "$pamBase/status" -Headers $pamHeaders
   $pamStatus
   ```

4. Only if you approve sending retrieved metadata (including names, IDs, timestamps
   and source links) to the displayed model destination, run:

   ```powershell
   $pamPermission = @{
       allow_read = $true
       allow_metadata_transfer = $true
       confirmed_destination = $pamStatus.model_destination
   } | ConvertTo-Json
   Invoke-RestMethod -Method Post -Uri "$pamBase/permissions" -Headers $pamHeaders -ContentType 'application/json' -Body $pamPermission
   ```

5. Start the conversation CLI and try metadata-only requests:

   ```powershell
   .venv\Scripts\python.exe -m pam.conversation.cli
   ```

   ```text
   Find the Drive file PAM TEST and tell me its type and modification time.
   Find PAM TEST and also show my Calendar availability for 19–25 October 2026.
   ```

6. After withdrawing metadata-transfer permission through `/permissions`, a
   sensitive follow-up must be denied; `/new` starts without that history.
   Changed saved permissions are loaded on the next request. A new model/endpoint
   also requires fresh consent. `/status` is configuration-only and does not
   decrypt the grant or claim a live connection.

Existing direct MCP commands remain metadata-read diagnostics and do not require
model-transfer permission because they do not invoke a model. Document-content
requests remain unsupported until the later content stage.

## Tests, documentation and checkpoint

48 new offline tests in `test_drive_routing.py` and
`test_drive_routing_clients.py` cover ordered search→metadata→Calendar transcripts,
both provider serializers, exact tool/result contracts, missing/wrong-owner/
destination/revoked permission, revocation during calls, sensitive follow-ups,
`/new`, context accumulation, six-call/two-Calendar limits, references/cursors,
partial failures, duplicate IDs, parallel calls and hostile metadata attempting
write/memory actions. An integration test uses the real Drive reader, real MCP
SDK/client and scripted model with fake Google responses.

All 408 tests pass, including prior Calendar, CLI, Telegram, memory, OAuth and MCP
regressions. Ruff lint/format, strict mypy, documentation links and Git whitespace
checks pass. CLI status was checked with local settings. Hosted-model Drive
conversation acceptance remains pending explicit saved metadata-transfer consent;
no real model calls, credential changes or new Google scopes were performed.

Next: Stage 8 improves conversational file references, transport UX and the
existing shared-memory integration with separately approved persistence rules.
