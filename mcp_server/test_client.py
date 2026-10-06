# -*- coding: utf-8 -*-
"""MCP 包装器的连通性测试:以 stdio 客户端身份拉起 server.py,
验证 tools 清单和 list_visited 实调。用法:
    .venv/Scripts/python.exe test_client.py
"""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command=r".venv\Scripts\python.exe", args=["server.py"])


async def main() -> None:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            print(f"== tools({len(tools)}) ==")
            for t in tools:
                print(f"- {t.name}: {(t.description or '').splitlines()[0][:50]}")

            print("\n== call list_visited ==")
            result = await session.call_tool("list_visited", {})
            print(result.content[0].text[:300])

            print("\n== call get_cached_detail(漫游器) ==")
            result = await session.call_tool("get_cached_detail", {"word": "漫游器"})
            print(result.content[0].text[:200])


if __name__ == "__main__":
    asyncio.run(main())
