import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "pravoved.mcp_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for t in tools.tools:
                print(t.name)
            res = await session.call_tool("get_key_rate", {})
            print(res.content[0].text)
            res = await session.call_tool("calc_salary_delay", {"amount": 50000, "due_date": "2026-07-10", "paid_date": "2026-08-05"})
            print(res.content[0].text)


asyncio.run(main())
