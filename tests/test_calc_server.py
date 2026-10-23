import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def list_tool_names():
    params = StdioServerParameters(command=sys.executable, args=["-m", "pravoved.mcp_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {t.name for t in tools.tools}


def test_server_lists_tools():
    names = anyio.run(list_tool_names)
    assert {"get_key_rate", "calc_consumer_penalty", "calc_salary_delay", "calc_deadline",
            "save_case", "list_cases"} <= names
