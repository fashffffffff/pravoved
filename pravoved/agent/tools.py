import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

# сохранение дел агенту не отдаём: побочные эффекты без спроса не нужны
HIDDEN = {"save_case", "list_cases"}
# веб-инструменты вызывает только шаг web в графе: модель в ответе не должна сама тянуть непроверенные страницы
WEB_TOOLS = {"web_search", "read_page"}


async def load_tools():
    url = os.environ.get("MCP_URL")
    if url:
        conf = {"transport": "streamable_http", "url": url}
    else:
        conf = {"transport": "stdio", "command": sys.executable, "args": ["-m", "pravoved.mcp_server"]}
    client = MultiServerMCPClient({"pravoved": conf})
    tools = await client.get_tools()
    return [t for t in tools if t.name not in HIDDEN]
