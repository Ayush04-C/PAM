# Stage 3: Drive configuration and offline status

Stage 3 adds safe configuration and a visible local diagnostic command. It
builds on [Stage 1 boundaries](STAGE_01_BOUNDARIES.md) and
[Stage 2 consent](STAGE_02_CONSENT.md), using the existing Settings,
ConversationService, CLI, and Telegram composition. Drive OAuth and MCP tools
remain future work.

## Settings and limits

| Environment variable | Default | Rule |
| --- | --- | --- |
| `PAM_DRIVE_CREDENTIAL_STORAGE_PATH` | `.pam-drive-credentials.bin` | Must resolve to a different path from Calendar credentials. |
| `PAM_DRIVE_MAX_CONTEXT_CHARS` | `20000` | Integer from 1 through 20000. |

The credential setting reserves a location; Stage 3 does not read, decrypt,
or create credentials. The default filename is ignored by Git. If you choose
a custom location, keep it outside tracked files or add an ignore rule.
Resolved-path comparison catches relative/absolute aliases and `..`; it does
not detect different hard links to the same file. Invalid or unresolvable
paths fail configuration validation.

CLI and Telegram pass the same configured context limit to ConversationService.
Oversized Drive text returns a fixed error before memory operations, tool
discovery, model calls, or history changes. The limit counts Python text
characters in the supplied DriveContext, not tokens, serialized prompts, or
the whole conversation. Stage 2's 20000-character hard ceiling and consent
checks still apply. A smaller limit does not grant permission or trim text
silently.

## Try the status command

From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -m pam.conversation.cli --status
```

For example, with a configured BharatCode provider and Google Calendar backend:

```text
Model provider: bharatcode
Model configuration: present
Calendar backend: google
Drive tools: not implemented
Drive model-transfer consent: not collected by CLI
Drive context limit: 20000 characters
Live connectivity: not checked
```

Values reflect validated settings. `present` means the selected provider's
required configuration exists; it does not verify the key, authentication,
connectivity, or consent. Fake mode reports `offline fake provider`.
The standalone command does not construct model, MCP, or memory clients, start
an event loop, or enter the input loop. It never opens credential files.
Normal configuration requirements still apply, including production, Calendar,
model, memory, and Telegram requirements when selected. Invalid settings print
`Invalid PAM configuration. Check your settings.` to stderr and exit with code 2;
raw validation errors and rejected values are not printed.

The same report is available through `/status` in an already running conversation
CLI. That command makes no model call. The normal CLI still constructs its
dependencies at startup, and `/new` still resets conversation history.

No keys, paths, owner IDs, or model endpoint URLs appear in status output.
There is no consent collection interface yet; settings and diagnostics cannot
authorize a Drive read or transfer. Calendar remains the only callable MCP
capability at this stage.

## Verification

Tests live in `pam/tests/test_config.py`, `test_drive_consent.py`, and the new
`test_cli.py`. They cover defaults without credential creation, environment
range validation, normalized credential path collisions, context denial before
side effects, exact-limit acceptance with consent, transport wiring, offline
status output, sanitized configuration errors, `/status`, ordinary turns, and
`/new` history reset. Existing Stage 2 denial, destination, owner, and memory
provenance cases remain part of the full regression suite.

Validation: 208 tests pass; Ruff lint and formatting, strict mypy, and Git
whitespace checks pass. The standalone status command was also exercised with
the local configuration. Tests use fake providers and do not validate live
Google or model connectivity.
