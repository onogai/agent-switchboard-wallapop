"""Private Streamable HTTP bridge for upstream's stdio-only MCP server."""

import os

from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy


# FastMCP starts the pinned upstream executable on demand. Each backend
# request gets an isolated stdio session; the account state lives on /data.
session_env = {
    key: value
    for key in (
        "WALLAPOP_BROWSER_SESSION_TOKEN",
        "WALLAPOP_DEVICE_ID",
        "WALLAPOP_DEVICE_FGP",
        "WALLAPOP_ACCESS_TOKEN",
        "WALLAPOP_REFRESH_TOKEN",
    )
    if (value := os.environ.get(key))
}

transport = StdioTransport(
    command="wallapop-mcp",
    args=["--allow-writes", "--session", "/data"],
    env={"WALLAPOP_CONFIG_DIR": "/data", **session_env},
    keep_alive=False,
)
bridge = create_proxy(transport, name="Wallapop stdio bridge")

if __name__ == "__main__":
    bridge.run(transport="http", host="0.0.0.0", port=8768)
