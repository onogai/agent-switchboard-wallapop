"""No account/network calls: check auth, MCP contract and a local tool."""
import asyncio
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main():
    url = sys.argv[1]
    token = Path(sys.argv[2]).read_text().strip()
    payload = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}).encode()
    for auth in ("", "Bearer invalid"):
        headers = {"Accept":"application/json, text/event-stream","Content-Type":"application/json"}
        if auth:
            headers["Authorization"] = auth
        try:
            urllib.request.urlopen(urllib.request.Request(url, payload, headers), timeout=10)
        except urllib.error.HTTPError as error:
            assert error.code == 401, error.code
        else:
            raise AssertionError("Unauthenticated request accepted")
    expected = set(json.loads(sys.argv[3]))
    assert len(expected) == 32
    assert {"list_saved_searches", "saved_search_results"} <= expected
    start = time.monotonic()
    async with Client(StreamableHttpTransport(url, headers={"Authorization":"Bearer "+token})) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert names == expected, (names - expected, expected - names)
        for _ in range(2):
            result = await client.call_tool("session_status", {})
            assert not result.is_error
            data = result.structured_content or json.loads(result.content[0].text)
            assert data["writes_enabled"] is True
            assert data["logged_in"] is False
    print(f"PASS auth, {len(names)} tools, repeated local status; {time.monotonic()-start:.2f}s")
    for index in range(2):
        start = time.monotonic()
        async with Client(StreamableHttpTransport(url, headers={"Authorization": "Bearer " + token})) as client:
            result = await client.call_tool("session_status", {})
            assert not result.is_error
            data = result.structured_content or json.loads(result.content[0].text)
            assert data["writes_enabled"] is True
            assert data["logged_in"] is False
        print(f"PASS fresh session {index+1}; {time.monotonic()-start:.2f}s")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 60))
