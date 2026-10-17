# Stage 1: Integration boundaries

Drive development stays in this folder. Start with the
[implementation plan](GOOGLE_DRIVE_IMPLEMENTATION_PLAN.md) and
[workflow diagrams](GOOGLE_DRIVE_ARCHITECTURE.md). This stage defines separation
and adds offline import checks; it does not enable Drive or change runtime code.
The revised design below supersedes the earlier independent-server proposal.

## Ownership

| Area | Owns | Boundary |
| --- | --- | --- |
| Calendar | Existing `pam/mcp/calendar.py` and Calendar services | Keep availability math, validation, tool schema and deterministic presentation intact. |
| Drive | Proposed `pam/mcp/driver.py` | Define validated read-only Drive tools, reusing existing suitable functions. Add a Drive API adapter only where new behavior is needed. |
| Shared MCP server | Existing `pam/mcp/server.py` | Register both tool families once implemented. Invoke only the authorized tools needed for a request; neither capability requires the other's credentials. |
| Shared infrastructure | Existing settings, logging, encryption, Google and MCP helpers | Extend or import existing code where its semantics fit; extract a helper only when necessary. No forced parallel infrastructure. |
| Conversation/composition | Existing `pam/conversation`, CLI and Telegram composition | Later dispatch approved tool names and combine results. MCP adapters do not call providers, Telegram or durable memory themselves. |

Keep one repository, one MCP server and the entry point `python -m pam.mcp.server`.
Today it exposes only `get_weekly_availability`; a later stage adds `drive_` tools
from `pam/mcp/driver.py`. The Calendar response remains `availability` plus
deterministic `presentation`. No separate `pam/drive` package, server process or
empty scaffolding is needed. `driver.py` and server registration are future runtime
work, not part of this Stage 1 revision.

Reusable now: encryption/store mechanics, settings/logging infrastructure,
provider-neutral tool values and the typed MCP launch descriptor. The existing
Calendar OAuth client hardcodes scopes, and the Calendar MCP client validates an
availability response: verify and adapt those semantics before reusing them for
Drive. Existing Calendar files may host reusable helpers; imports between feature
files are allowed when useful. Avoid duplicate implementations and import cycles.
Shared code does not mean sharing Calendar scopes or overwriting its credentials.
Combined requests use the existing orchestrator with validated tool dispatch in a
later stage, not a second server registry. Tool failures should remain specific
to their capability; an outage of the shared MCP transport can affect both.

## Tests and error handling

[`test_integration_boundaries.py`](../../pam/tests/test_integration_boundaries.py)
checks ordinary Python imports in the real source tree. It rejects MCP adapters →
conversation orchestration/model-provider, Telegram or memory, and Calendar domain
→ MCP adapters. Plain shared values from `pam.conversation.models`, including the
consent types, remain reusable by adapters.
It explicitly allows the shared server to import both adapters and allows Drive
to reuse existing Calendar-file helpers. Whether a helper's behavior is suitable
must be reviewed and tested at the reuse site; file location alone is not a ban.
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

- Adapter/domain coupling: checked by import guards and existing Calendar regressions.
- Scope/credential disruption: no OAuth, settings or credential changes in Stage 1.
- Production resource impact: no runtime code, services, dependencies or deployment changes.
- Secret exposure: tests are offline; do not read real credential files or log payloads.
- Future content/model/memory risks: mandatory consent and later runtime tests,
  not claimed as resolved by this stage.

Stage 1 is complete after the new tests, existing regression suite, format/lint/type
checks, documentation links and whitespace checks pass. Record actual outcomes
in the stage handoff; a blocked check is not a passing gate. No production rollout
is part of this stage.

Validation on 2026-10-17: 159 tests passed, including 16 revised boundary checks;
format, lint, type and whitespace checks passed.
Existing async tests require running outside the Windows sandbox
because its loopback socket restriction stalled event-loop setup. No tests were
skipped or application code changed to work around that restriction.

## Next: Stage 2, consent and LLM boundaries

See the implemented [Stage 2 boundary and its limits](STAGE_02_CONSENT.md).

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
