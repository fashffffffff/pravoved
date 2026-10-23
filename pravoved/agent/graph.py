import json
import operator
import re
import time
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from pravoved.agent import prompts
from pravoved.agent.verify import check_citations
from pravoved.retrieval.search import search

MAX_RETRIES = 2
MAX_SOURCES = 10
MAX_TOOL_STEPS = 5
SNIPPET = 1500


class State(TypedDict, total=False):
    question: str
    queries: list
    hits: list
    retries: int
    enough: bool
    retry: bool
    out_of_scope: bool
    where: str
    strict: bool
    regenerated: bool
    again: bool
    refused: bool
    answer: str
    sources: list
    tool_calls: list
    cited: int
    invalid: int
    warning: str
    usage: Annotated[list, operator.add]


def hit_key(h):
    return (h.law, h.article, h.part)


def format_source(i, h):
    part = ", ч. " + h.part if h.part else ""
    return "[%d] %s%s. %s\n%s" % (i, h.citation, part, h.title, h.text[:SNIPPET])


def source_list(hits):
    return "\n\n".join(format_source(i, h) for i, h in enumerate(hits, 1))


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def usage_of(msg, seconds):
    meta = getattr(msg, "usage_metadata", None) or {}
    return {"prompt": meta.get("input_tokens", 0), "completion": meta.get("output_tokens", 0), "seconds": seconds}


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def tool_result_text(result):
    if isinstance(result, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


def build_graph(llm, tools):
    tools_by_name = {t.name: t for t in tools}
    llm_tools = llm.bind_tools(tools) if tools else llm

    def retrieve(state):
        query = state["queries"][-1]
        old = state.get("hits", [])
        seen = {hit_key(h) for h in old}
        new = [h for h in search(query, k=8) if hit_key(h) not in seen]
        # новые найденные ставим после старых, лишнее отрезаем
        return {"hits": (old + new)[:MAX_SOURCES]}

    async def grade(state):
        hits = state["hits"]
        context = "\n\n".join("- %s. %s: %s" % (h.citation, h.title, h.text[:300].replace("\n", " ")) for h in hits)
        msgs = [SystemMessage(prompts.GRADE_SYSTEM),
                HumanMessage(prompts.GRADE_USER.format(question=state["question"], context=context))]
        t = time.time()
        msg = await llm.ainvoke(msgs)
        usage = [usage_of(msg, time.time() - t)]
        data = parse_json(strip_think(msg.content))
        if data is None:
            # модель не выдала json - не отказываем зря
            return {"enough": True, "retry": False, "out_of_scope": False, "usage": usage}
        out = bool(data.get("out_of_scope"))
        enough = bool(data.get("enough")) and not out
        update = {"enough": enough, "retry": False, "out_of_scope": out, "where": str(data.get("where") or ""), "usage": usage}
        new_query = str(data.get("query") or "").strip()
        if not enough and not out and state.get("retries", 0) < MAX_RETRIES and new_query:
            update["queries"] = state["queries"] + [new_query]
            update["retries"] = state.get("retries", 0) + 1
            update["retry"] = True
        return update

    def after_grade(state):
        if state["enough"]:
            return "answer"
        return "retrieve" if state["retry"] else "refuse"

    def refuse(state):
        where = state.get("where") or prompts.DEFAULT_WHERE
        return {"answer": prompts.REFUSAL.format(where=where), "refused": True, "sources": [],
                "tool_calls": [], "cited": 0, "invalid": 0}

    async def answer(state):
        hits = state["hits"]
        system = prompts.ANSWER_SYSTEM.format(today=date.today().strftime("%d.%m.%Y"))
        if state.get("strict"):
            system += prompts.STRICT_ADD
        user = prompts.ANSWER_USER.format(sources=source_list(hits), question=state["question"])
        msgs = [SystemMessage(system), HumanMessage(user)]
        calls = []
        usage = []
        text = ""
        for _ in range(MAX_TOOL_STEPS):
            t = time.time()
            msg = await llm_tools.ainvoke(msgs)
            usage.append(usage_of(msg, time.time() - t))
            msgs.append(msg)
            text = strip_think(msg.content if isinstance(msg.content, str) else "")
            if not msg.tool_calls:
                break
            for call in msg.tool_calls:
                result = await run_tool(call)
                calls.append({"name": call["name"], "args": call["args"], "result": result})
                msgs.append(ToolMessage(content=result, tool_call_id=call["id"]))
        return {"answer": text, "tool_calls": calls, "usage": usage}

    async def run_tool(call):
        tool = tools_by_name.get(call["name"])
        if tool is None:
            return "Ошибка: нет инструмента " + call["name"]
        try:
            return tool_result_text(await tool.ainvoke(call["args"]))
        except Exception as e:
            # ошибку отдаём модели, пусть исправит аргументы
            return "Ошибка инструмента: %s" % e

    def verify(state):
        tool_text = "\n".join(c["result"] for c in state["tool_calls"])
        text, cited, invalid, used = check_citations(state["answer"], state["hits"], tool_text)
        sources = []
        for n in used:
            h = state["hits"][n - 1]
            sources.append({"n": n, "citation": h.citation, "law": h.law, "article": h.article,
                            "snippet": h.text[:200].replace("\n", " ")})
        update = {"answer": text, "sources": sources, "cited": cited, "invalid": invalid, "again": False}
        if sources or state["tool_calls"]:
            return update
        if not state.get("regenerated"):
            return {"strict": True, "regenerated": True, "again": True}
        update["warning"] = "В ответе нет подтверждённых ссылок на источники, проверьте его самостоятельно."
        return update

    def after_verify(state):
        return "answer" if state["again"] else "end"

    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("refuse", refuse)
    g.add_node("answer", answer)
    g.add_node("verify", verify)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["retrieve", "answer", "refuse"])
    g.add_edge("refuse", END)
    g.add_edge("answer", "verify")
    g.add_conditional_edges("verify", after_verify, {"answer": "answer", "end": END})
    return g.compile()
