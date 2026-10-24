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


def test_penalty_tool_dates():
    from pravoved.mcp_server.server import calc_consumer_penalty
    # привезти должны были 1 марта, привезли 11 марта: 10 дней
    res = calc_consumer_penalty(price=70000, kind="prepaid_delivery", due_date="2026-03-01", actual_date="2026-03-11")
    assert res["days"] == 10
    assert res["penalty"] == "3500.00"


def test_penalty_tool_needs_days_or_dates():
    import pytest
    from pravoved.mcp_server.server import calc_consumer_penalty
    with pytest.raises(ValueError):
        calc_consumer_penalty(price=1000)


def test_deadline_tool_counts_from_next_day():
    from pravoved.mcp_server.server import calc_deadline
    # куртка куплена 4 мая 2026, 14 дней: 18 мая (пн)
    assert calc_deadline(event_date="2026-05-04", kind="exchange_14")["deadline"] == "2026-05-18"
