# Stage 1: Integration boundaries

Drive development stays in this folder. Start with the
[implementation plan](GOOGLE_DRIVE_IMPLEMENTATION_PLAN.md) and
[workflow diagrams](GOOGLE_DRIVE_ARCHITECTURE.md). This stage defines separation
and adds offline import checks; it does not enable Drive or change runtime code.

## Ownership

| Area | Owns | Boundary |
| --- | --- | --- |
| Existing Calendar | `pam/domain`, `pam/application`, Calendar integration/wiring and `pam/mcp/calendar.py`, `server.py` | No dependency on `pam.drive`. Keep availability math, validation and presentation here. |
| Proposed Drive | `pam/drive` with its own `mcp/server.py` | File models, API reads and strict Drive tools. No Calendar, conversation/model-provider, Telegram or memory imports. |
| Shared infrastructure | `pam/config.py`, `pam/logging.py`, `pam/security`; future extracted `pam/integrations/google_oauth.py` | No Calendar or Drive domain dependencies. Reuse mechanics, not domain policy. |
| Conversation/composition | `pam/conversation`, CLI and Telegram composition | May construct both capabilities. Later routing validates model-proposed tool calls and combines results. |

Keep one repository and one installed PAM package. Calendar retains the entry
point `python -m pam.mcp.server` and the single `get_weekly_availability` tool.
Its structured response remains `availability` plus deterministic `presentation`.
Drive will have `python -m pam.drive.mcp.server` and `drive_` tool names when its
server stage is implemented. No Drive package or empty scaffolding is added now.

Reusable now: encryption/store mechanics, settings/logging infrastructure,
provider-neutral tool values and the typed MCP launch descriptor. The existing
Calendar OAuth client hardcodes scopes, and the Calendar MCP client validates an
availability response: neither is a generic Drive client. Scope-aware OAuth
extraction, separate credential paths and multi-MCP routing belong to later stages.
Drive must never overwrite Calendar credentials. Combined requests will go through
the shared orchestrator, not directly between the two capability packages.

## Tests and error handling

[`test_integration_boundaries.py`](../../pam/tests/test_integration_boundaries.py)
checks ordinary Python imports in the real source tree. It rejects Calendar →
Drive, Drive → Calendar/model/transport/memory, and shared → domain dependencies.
Fixtures cover direct, aliased, parent-package and relative imports, allowed
reuse/composition, and invalid syntax. Violations report file, line and imported
module; read/parse errors fail the check rather than silently skipping source.
The checks parse source without importing it or evaluating application settings.

These are dependency guardrails, not a security sandbox: they do not resolve
transitive dependencies, arbitrary dynamic imports or runtime behavior. Drive is
not implemented, so passing fixtures do not prove future Drive runtime isolation.
Existing Calendar MCP tests remain the authority for schemas, read-only tool
discovery, safe failures and exact deterministic output; they are reused rather
than duplicated here. Existing conversation, memory and Telegram tests cover
their current contracts, not future Drive data handling.

Run from the repository root using the existing environment:

```text
python -m pytest -q pam/tests/test_integration_boundaries.py
python -m ruff format --check .
python -m ruff check .
python -m mypy pam
python -m pytest
git diff --check
```

## Risks and completion gate

- Calendar coupling: checked by import guards and existing Calendar regressions.
- Scope/credential disruption: no OAuth, settings or credential changes in Stage 1.
- Production resource impact: no runtime code, services, dependencies or deployment changes.
- Secret exposure: tests are offline; do not read real credential files or log payloads.
- Future content/model/memory risks: mandatory consent and later runtime tests,
  not claimed as resolved by this stage.

Stage 1 is complete after the new tests, existing regression suite, format/lint/type
checks, documentation links and whitespace checks pass. Record actual outcomes
in the stage handoff; a blocked check is not a passing gate. No production rollout
is part of this stage.

Validation on 2026-10-17: 165 tests passed, including 22 boundary checks;
format/lint/type checks, 91 local documentation links/anchors and whitespace
checks passed. Existing async tests required running outside the Windows sandbox
because its loopback socket restriction stalled event-loop setup. No tests were
skipped or application code changed to work around that restriction.

## Next: Stage 2, consent and LLM boundaries

Before live Drive data reaches the configured model, approve its actual local or
hosted deployment, permitted data transfer, read-only capabilities, retention,
logging and memory exclusions. Communicate constraints through system instructions
and tool schemas, and enforce them in code: an API key alone cannot enforce them.
Documents are untrusted data and cannot authorize tools or memory writes.

Each later stage stays small: agree on scope, implement with relevant tests and
safe errors, update these focused docs, validate, then review before proceeding.
Stage 1 covers the integration-contract portion of the original D0. Stage 2 makes
the original cross-cutting consent/security requirements an explicit early gate;
the remaining D1–D7 plan continues to guide later implementation.
