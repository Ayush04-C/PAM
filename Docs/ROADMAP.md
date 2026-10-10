# Roadmap

This page intentionally distinguishes proposals from implemented PAM behavior. The current system has one private, read-only local Calendar MCP tool; it does not have a public multi-service MCP platform or Google Drive integration.

## Proposed Phase 12 — Google Drive read-only integration

Add an **existing MCP-based Google Drive read-only integration** after a separate design and security review. Scope should be limited to explicit read/search/list actions with least-privilege Drive OAuth scopes. Required decisions include owner identity mapping, allowed file types, result-size and content limits, document-sharing semantics, credential storage, audit logging, and a clear model-tool allowlist.

## Proposed Phase 13 — conversational Drive file intelligence

Build conversational understanding on top of an approved read-only Drive integration. This is not simply a model prompt: it requires retrieval bounds, provenance in responses, prompt-injection handling for document content, privacy/retention decisions, access-control rechecks for every result, and tests for cross-user and cross-file leakage.

## Proposed Phase 14 — expanded/custom MCP architecture

Evaluate independently deployed or custom MCP services only after defining authentication, service discovery, transport security, tenant/owner isolation, tool schemas, authorization policy, timeouts, retries, auditability, versioning, and incident revocation. A future remote MCP service must not inherit trust merely because it uses MCP; every tool needs explicit least-privilege policy.

## Non-goals until separately approved

* Calendar write operations or autonomous scheduling.
* A public unauthenticated MCP endpoint.
* Automatic provider fallback that changes data-sharing or cost behavior.
* Treating remembered or retrieved content as authoritative instructions.
