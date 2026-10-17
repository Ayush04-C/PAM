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

## Replacement-key diagnostic and handoff, 2026-10-18

The operator replaced the BharatCode key in `.env`. A fresh diagnostic process
confirmed that its effective key matched the file without printing either value.
The application did not rotate or modify credentials. The operator also confirmed
student verification; the displayed allowance does not establish remaining quota
or successful generation.

| Synthetic check | Result |
| --- | --- |
| `GET /models` with the replacement key | Successful in approximately 2 seconds; configured Qwen model listed |
| `/chat/completions`, short greeting | `APITimeoutError` after 20.1 seconds; no HTTP status returned |
| `/responses`, short greeting with `store:false` | `APITimeoutError` after 20.1 seconds; no HTTP status returned |

Both generation probes disabled SDK retries and sent no Drive data. These results
do not confirm an invalid key, exhausted quota, subscription denial or a specific
provider outage. Catalog authentication succeeded, while generation remained
unverified. Replacing the key did not resolve the observed timeout. No further
key rotation, model change or automatic fallback is justified by these results.

Live acceptance is deferred at the operator's request until a later session when
generation is available. No scheduled retry or deployment is configured. For a
provider support request, share the model, endpoint paths, elapsed times and
exception type above; never include the key or the contents of `.env`.

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

Restart any existing CLI process after editing `.env`, so it loads the current
key. Resume acceptance in this order:

1. Confirm a plain greeting returns a complete model answer.
2. Search for `PAM TEST` and confirm numbered file choices appear.
3. Request metadata for a returned choice, then summarize a supported test file
   with source passages, subject to the existing transfer permissions.
4. Ask a combined Drive and Calendar question and verify both sources and facts.
5. Verify `/new` clears temporary choices, and repeat owner-specific checks for
   Telegram before considering deployment.

Record the actual outcomes before marking these gates complete. A working direct
MCP search alone does not satisfy model-driven conversation acceptance.

Offline verification: 529 tests pass, including timeout classification, configured
deadline forwarding, no sensitive error leakage, no choices after initial timeout
and verified Calendar fallback after a later timeout. Ruff and strict mypy pass.
Remaining Stage 10 gates are completed model/Drive conversations, CLI/Telegram
owner-specific acceptance, CI/release checks, Azure measurements and rollback.
