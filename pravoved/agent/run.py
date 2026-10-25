import os
import tempfile
import time
from pathlib import Path

from pravoved.agent import contract
from pravoved.agent.graph import build_graph
from pravoved.agent.llm import make_llm
from pravoved.agent.tools import call_tool, load_tools

# llm и инструменты последнего созданного агента, нужны проверке договора и претензиям
kit = {}


def total_usage(usage):
    prompt = sum(u["prompt"] for u in usage)
    completion = sum(u["completion"] for u in usage)
    seconds = sum(u["seconds"] for u in usage)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "llm_seconds": round(seconds, 2),
            "tokens_per_sec": round(completion / seconds, 1) if seconds and completion else None}


async def make_agent():
    kit["llm"] = make_llm()
    kit["tools"] = await load_tools()
    return build_graph(kit["llm"], kit["tools"])


async def ask(graph, question, on_step=None):
    """Прогоняет вопрос через граф. on_step(имя_узла, обновление) - для режима --debug."""
    start = time.time()
    final = None
    async for mode, data in graph.astream({"question": question, "queries": [question], "retries": 0, "hits": []},
                                          stream_mode=["updates", "values"]):
        if mode == "updates" and on_step:
            for node, update in data.items():
                on_step(node, update)
        if mode == "values":
            final = data
    return {
        "question": question,
        "answer": final["answer"],
        "refused": final.get("refused", False),
        "sources": final.get("sources", []),
        "tool_calls": final.get("tool_calls", []),
        "queries": final["queries"],
        "cited": final.get("cited", 0),
        "invalid": final.get("invalid", 0),
        "unverified_cited": final.get("unverified_cited", 0),
        "unbacked_numbers": final.get("unbacked_numbers", 0),
        "web_used": bool(final.get("web_sources")),
        "warning": final.get("warning"),
        "seconds": round(time.time() - start, 2),
        **total_usage(final.get("usage", [])),
    }


def save_temp(filename, data):
    fd, path = tempfile.mkstemp(suffix=Path(filename).suffix.lower())
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


async def read_scan(filename, data):
    """Текст из скана, фото или pdf (байты файла). -> строка"""
    path = save_temp(filename, data)
    try:
        res = await call_tool(kit["tools"], "read_scan", {"path": path})
    finally:
        os.unlink(path)
    if "error" in res:
        raise ValueError(res["error"])
    return res["text"]


async def check_contract(graph, filename, data, on_progress=None):
    """Проверка договора по пунктам. data - байты файла (txt, docx, pdf, jpg, png).
    Возвращает dict: kind, clauses (id, text, section, color, reason, cites), counts, top_risks, markdown, seconds."""
    path = save_temp(filename, data)
    try:
        text = await contract.read_file(path, kit["tools"])
    finally:
        os.unlink(path)
    return await check_contract_text(text, filename, on_progress)


async def check_contract_text(text, filename="", on_progress=None):
    res = await contract.check_contract(kit["llm"], text, on_progress)
    res["filename"] = filename
    return res
