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


def test_penalty_tool_paid_cap():
    from pravoved.mcp_server.server import calc_consumer_penalty
    res = calc_consumer_penalty(price=50000, days=200, paid=30000)
    assert res["penalty"] == "30000.00"
    assert res["capped"]
    assert calc_consumer_penalty(price=50000, days=10)["penalty"] == "5000.00"
