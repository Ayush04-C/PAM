# Local Calendar MCP setup

Phase 5 provides one private local MCP server over **stdio**. Stdio keeps the
server process-local and gives a future Phase 7 agent a small launch boundary;
PAM does not expose MCP over the network.

Run the server from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pam.mcp.server
```

The process communicates with an MCP client over standard input/output, so do
not use a browser to call it directly. The only discoverable tool is:

`get_weekly_availability`

To discover tools and invoke the server from a local Python MCP client:

```python
import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main() -> None:
    launch = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pam.mcp.server"],
    )
    async with Client(launch) as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools.tools])
        result = await client.call_tool(
            "get_weekly_availability",
            {
                "start_date": "2026-09-28",
                "end_date": "2026-10-04",
                "timezone": "Asia/Kolkata",
            },
        )
        print(result.structured_content)


asyncio.run(main())
```

Example tool arguments:

```json
{
  "start_date": "2026-09-28",
  "end_date": "2026-10-04",
  "timezone": "Asia/Kolkata"
}
```

The tool is read-only. It delegates to `AvailabilityService`, accepts only
explicit validated ranges, and returns the same deterministic `availability`
summary as `POST /availability`. Application range limits still apply.

For offline development, leave `PAM_CALENDAR_BACKEND=fake`. For Google mode,
use the existing ignored `.env` configuration and encrypted credentials from
[LOCAL_GOOGLE_OAUTH.md](LOCAL_GOOGLE_OAUTH.md). No new OAuth or credential
interface is exposed by MCP.

A future Phase 7 agent can launch the local process using the typed
`local_stdio_launch_config(...)` helper in `pam.mcp.config`; Phase 5 does not
implement that agent.
