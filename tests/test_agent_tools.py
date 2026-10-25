import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pravoved.mcp_server import server


async def list_tool_names():
    params = StdioServerParameters(command=sys.executable, args=["-m", "pravoved.mcp_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {t.name: t for t in tools.tools}


def test_new_tools_registered():
    tools = anyio.run(list_tool_names)
    assert {"draft_claim", "add_to_calendar", "read_scan"} <= set(tools)
    # описание инструмента - то, что видит модель
    assert "претензи" in tools["draft_claim"].description.lower()
    assert "kind" in tools["draft_claim"].inputSchema["properties"]


def test_draft_claim_missing_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    res = server.draft_claim(kind="consumer_refund", sender_name="Иванов Иван")
    assert "sender_address" in res["missing"]
    assert "date" not in res["missing"]


def test_draft_claim_and_calendar(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    res = server.draft_claim(kind="consumer_refund", sender_name="Иванов Иван", sender_address="г. Казань, ул. Мира, 1",
                             recipient="ООО «Магнит»", recipient_address="г. Казань, ул. Ленина, 5",
                             facts="Купил телефон, через неделю он сломался.", demand="Вернуть 30 000 рублей.")
    assert res["path"].endswith(".docx")
    assert "ПРЕТЕНЗИЯ" in res["preview"]
    ev = server.add_to_calendar("Срок ответа", "2026-11-05")
    assert ev["path"].endswith(".ics")
    assert (tmp_path / "event_20261105.ics").exists()


def test_read_scan_missing_file():
    assert "error" in server.read_scan("/no/such/file.jpg")
