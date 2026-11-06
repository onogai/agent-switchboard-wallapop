"""Check MCP discovery without making a Wallapop API request."""

import asyncio

from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8768/mcp") as client:
        names = {tool.name for tool in await client.list_tools()}
        if "session_status" not in names or "delete_item" not in names:
            raise RuntimeError("Wallapop read/write tools are unavailable")


if __name__ == "__main__":
    asyncio.run(main())
