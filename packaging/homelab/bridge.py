"""Private Streamable HTTP bridge for upstream's stdio-only MCP server."""

import os

from fastmcp.client.transports import StdioTransport
from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient


# Each proxy request needs its own transport. Reusing one StdioTransport across
# concurrent clients fails with "live session built for different connection
# options" and makes tool discovery intermittent.
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

def client_factory() -> ProxyClient:
    transport = StdioTransport(
        command="wallapop-mcp",
        args=["--allow-writes", "--session", "/data"],
        env={"WALLAPOP_CONFIG_DIR": "/data", **session_env},
        keep_alive=False,
    )
    return ProxyClient(transport, forward_incoming_headers=False)


bridge = FastMCPProxy(client_factory=client_factory, name="Wallapop stdio bridge")

if __name__ == "__main__":
    bridge.run(transport="http", host="0.0.0.0", port=8768)
