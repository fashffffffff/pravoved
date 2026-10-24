import time

from pravoved.agent.graph import build_graph
from pravoved.agent.llm import make_llm
from pravoved.agent.tools import load_tools


def total_usage(usage):
    prompt = sum(u["prompt"] for u in usage)
    completion = sum(u["completion"] for u in usage)
    seconds = sum(u["seconds"] for u in usage)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "llm_seconds": round(seconds, 2),
            "tokens_per_sec": round(completion / seconds, 1) if seconds and completion else None}


async def make_agent():
    return build_graph(make_llm(), await load_tools())


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
