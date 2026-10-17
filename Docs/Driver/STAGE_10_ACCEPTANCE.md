# Stage 10: live acceptance checkpoint

## Local diagnostic, 2026-10-18

The configured CLI owner now matches the Drive grant, and effective metadata and
content-transfer permissions are enabled. No permissions or credentials were
changed during this diagnostic.

The real shared MCP server discovered all three Drive tools. A direct bounded
search for the operator-approved `PAM TEST` returned one match successfully.
Only counts and safe statuses were recorded; retrieved metadata/content was not
sent to a model during the provider-isolation tests.

BharatCode's model catalog responded and listed the configured `qwen-3.8-27b`.
Synthetic plain chat and dummy-tool chat timed out at 20 seconds, then again at
90 seconds with retries disabled. The other catalog-listed model returned HTTP
403 to a synthetic request. Model settings and saved consent were left unchanged.
An 80-second bounded streaming tool-call probe received five chunks but no text,
tool call or completion signal before its deadline. Partial stream activity was
not counted as a successful generation.
Catalog reachability is not evidence of successful generation or account access
to every listed model. See the provider's [API guide](https://bharatcode.ai/build).

This is an incomplete live acceptance result. Drive MCP reads passed; an actual
model-driven file search, summary and combined Calendar answer are still pending.
No Azure deployment, Telegram poller startup or production change was performed.

## Safe errors and retry procedure

BharatCode SDK timeouts now raise a typed `ModelTimeout`, shown to the user as a
model-provider timeout. The application preserves a verified Calendar partial
answer when available and does not commit a failed answer or new file choices.
Raw provider bodies, request data and credentials remain hidden.

`PAM_BHARATCODE_TIMEOUT_SECONDS` can override the existing 30-second per-request
default within 5–180 seconds. One SDK retry still applies. No local `.env` value
was changed, and a longer deadline is not a remedy for an unhealthy upstream.
No automatic model fallback is performed, because changing the model changes
the approved Drive data-transfer destination.

From Windows Command Prompt, after provider generation is available:

```cmd
cd /d D:\Learning\PAM
.venv\Scripts\python.exe -m pam.conversation.cli
```

Start with `/new`, then a plain greeting, followed by `Find PAM TEST`. Continue
with `file 1` only after a successful search displays numbered choices. If the
first model request fails, `file 1` is unavailable because no search completed.
Existing [Stage 9](STAGE_09_CONTENT.md) consent and format requirements still apply.

Offline verification: 529 tests pass, including timeout classification, configured
deadline forwarding, no sensitive error leakage, no choices after initial timeout
and verified Calendar fallback after a later timeout. Ruff and strict mypy pass.
Remaining Stage 10 gates are completed model/Drive conversations, CLI/Telegram
owner-specific acceptance, CI/release checks, Azure measurements and rollback.
