# PAM technical documentation

This directory describes the implementation that exists in the current PAM
repository. Source code and tests are the authority when a guide and the
running application disagree. Configuration examples deliberately use names
only: put values in an ignored `.env` file or the production service
environment.

## Recommended reading order

1. [Architecture](ARCHITECTURE.md) for components, boundaries, and request
   flows.
2. [Conversation and models](CONVERSATION_AND_MODELS.md) for the assistant
   loop and presentation contract.
3. [Google Calendar integration](GOOGLE_CALENDAR_INTEGRATION.md) before
   configuring live Calendar access.
4. [MCP integration](MCP_INTEGRATION.md) for the private read-only Calendar
   tool.
5. [Memory integration](MEMORY_INTEGRATION.md) and
   [Telegram integration](TELEGRAM_INTEGRATION.md) for optional adapters.
6. [Production deployment](PRODUCTION_DEPLOYMENT.md) and
   [Testing and operations](TESTING_AND_OPERATIONS.md) for operating PAM.
7. [Roadmap](ROADMAP.md) for proposed work, not current behavior.

## Guides

| Area | Guide |
| --- | --- |
| System layout, trust, request flows | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Conversation orchestration and model providers | [CONVERSATION_AND_MODELS.md](CONVERSATION_AND_MODELS.md) |
| Google OAuth and Calendar reads | [GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md) |
| Private Calendar MCP server/client | [MCP_INTEGRATION.md](MCP_INTEGRATION.md) |
| Supermemory durable memory | [MEMORY_INTEGRATION.md](MEMORY_INTEGRATION.md) |
| Telegram polling adapter | [TELEGRAM_INTEGRATION.md](TELEGRAM_INTEGRATION.md) |
| Azure/PM2 deployment | [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) |
| Verification and incident runbooks | [TESTING_AND_OPERATIONS.md](TESTING_AND_OPERATIONS.md) |
| Proposed future phases | [ROADMAP.md](ROADMAP.md) |
| Availability presentation contract | [AVAILABILITY_PRESENTATION.md](AVAILABILITY_PRESENTATION.md) |

## Existing focused local guides

The `LOCAL_*.md` guides are concise setup notes retained for convenience:
[BharatCode](LOCAL_BHARATCODE.md), [conversation](LOCAL_CONVERSATION.md),
[conversation history](LOCAL_CONVERSATION_HISTORY.md),
[Google OAuth](LOCAL_GOOGLE_OAUTH.md), [MCP](LOCAL_MCP.md),
[Supermemory](LOCAL_SUPERMEMORY.md), and [Telegram](LOCAL_TELEGRAM.md).
They complement, rather than replace, the operational documentation above.
