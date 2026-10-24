import json
import operator
import os
import re
import time
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from pravoved.agent import prompts
from pravoved.agent.tools import WEB_TOOLS
from pravoved.agent.verify import check_citations, unverified_cited
from pravoved.mcp_server.web import TRUST_ORDER
from pravoved.retrieval.search import search

MAX_RETRIES = 2
MAX_SOURCES = 10
MAX_TOOL_STEPS = 5
SNIPPET = 1500
WEB_SNIPPET = 3500
MAX_WEB_PAGES = 3
SITES = " site:consultant.ru OR site:pravo.gov.ru OR site:garant.ru"
# вопросы про расчёты отвечают инструменты, а не поиск; маленькие модели в grade часто путают их с вопросами вне базы
CALC_WORDS = re.compile(r"ключев\w* ставк|неустойк|до какого числа|какого числа|когда (?:истека|законч)|компенсаци\w* за задержк", re.IGNORECASE)
# вопросы про свежие изменения и штрафы: локальная база их не знает, идём в интернет
WEB_WORDS = re.compile(r"нов\w+ закон|(?:с|в) (?:\d+ \w+ )?20[2-9]\d|измени[лт]\w*|изменени\w*|сейчас действу|штраф|коап", re.IGNORECASE)


class State(TypedDict, total=False):
    question: str
    queries: list
    hits: list
    retries: int
    enough: bool
    retry: bool
    out_of_scope: bool
    legal: bool
    need_web: bool
    web_sources: list
    unverified_cited: int
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


def format_web_source(i, w):
    date_part = ", дата: " + w["date"] if w.get("date") else ""
    head = "[%d] ВЕБ, доверие: %s, %s%s" % (i, w["trust"], w["url"], date_part)
    return "%s\n%s\n<<<\n%s\n>>>" % (head, w["title"], w["text"])


def source_list(hits, web=()):
    parts = [format_source(i, h) for i, h in enumerate(hits, 1)]
    parts += [format_web_source(i, w) for i, w in enumerate(web, len(hits) + 1)]
    return "\n\n".join(parts)


def web_enabled():
    return os.environ.get("WEB_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def relevant_part(text, question, limit):
    # длинная страница не влезает в промпт: берём абзацы, где больше слов из вопроса
    if len(text) <= limit:
        return text
    words = {w[:5] for w in re.findall(r"\w{4,}", question.lower())}
    parts = text.split("\n")
    order = sorted(range(len(parts)), key=lambda i: -sum(w in parts[i].lower() for w in words))
    keep, size = set(), 0
    for i in order:
        if size + len(parts[i]) < limit:
            keep.add(i)
            size += len(parts[i]) + 1
    return "\n".join(parts[i] for i in sorted(keep))


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
    answer_tools = [t for t in tools if t.name not in WEB_TOOLS]
    llm_tools = llm.bind_tools(answer_tools) if answer_tools else llm
    web_on = web_enabled() and WEB_TOOLS <= set(tools_by_name)

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
            return {"enough": True, "retry": False, "out_of_scope": False, "need_web": False, "usage": usage}
        out = bool(data.get("out_of_scope"))
        enough = bool(data.get("enough")) and not out
        legal = bool(data.get("legal", not out))
        calc = bool(CALC_WORDS.search(state["question"]))
        if calc:
            out, enough, legal = False, True, True
        need_web = legal and not calc and bool(WEB_WORDS.search(state["question"]))
        update = {"enough": enough, "retry": False, "out_of_scope": out, "legal": legal, "need_web": need_web,
                  "where": str(data.get("where") or ""), "usage": usage}
        new_query = str(data.get("query") or "").strip()
        if not enough and not out and state.get("retries", 0) < MAX_RETRIES and new_query:
            update["queries"] = state["queries"] + [new_query]
            update["retries"] = state.get("retries", 0) + 1
            update["retry"] = True
        return update

    def after_grade(state):
        if web_on and state["need_web"]:
            return "web"
        if state["enough"]:
            return "answer"
        if state["retry"]:
            return "retrieve"
        return "web" if web_on and state["legal"] else "refuse"

    async def call_json(name, args):
        return parse_json(await run_tool({"name": name, "args": args})) or {}

    async def web_queries(question):
        msgs = [SystemMessage(prompts.WEB_QUERY_SYSTEM), HumanMessage(question)]
        t = time.time()
        msg = await llm.ainvoke(msgs)
        data = parse_json(strip_think(msg.content)) or {}
        queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()][:2]
        return queries or [question], [usage_of(msg, time.time() - t)]

    async def web(state):
        question = state["question"]
        queries, usage = await web_queries(question)
        # плюс вариант с официальными сайтами - поисковик часто ставит их выше
        found = {}
        for q in queries + [queries[0] + SITES]:
            for r in (await call_json("web_search", {"query": q, "max_results": 6})).get("results", []):
                found.setdefault(r["url"], r)
        ranked = sorted(found.values(), key=lambda r: TRUST_ORDER.index(r["trust"]))
        pages = []
        for r in ranked[:MAX_WEB_PAGES]:
            page = await call_json("read_page", {"url": r["url"]})
            if not page.get("text"):
                continue
            pages.append({"url": r["url"], "title": page.get("title") or r["title"], "trust": r["trust"],
                          "date": page.get("date"), "text": relevant_part(page["text"], question, WEB_SNIPPET)})
        update = {"web_sources": pages, "usage": usage}
        if not state["enough"] and state.get("out_of_scope"):
            # локальные фрагменты не по теме, в ответ их не берём
            update["hits"] = []
        return update

    def after_web(state):
        return "answer" if state["web_sources"] or state["enough"] else "refuse"

    def refuse(state):
        where = state.get("where") or prompts.DEFAULT_WHERE
        return {"answer": prompts.REFUSAL.format(where=where), "refused": True, "sources": [],
                "tool_calls": [], "cited": 0, "invalid": 0}

    async def answer(state):
        hits = state["hits"]
        web_sources = state.get("web_sources", [])
        system = prompts.ANSWER_SYSTEM.format(today=date.today().strftime("%d.%m.%Y"))
        if web_sources:
            system += prompts.WEB_ADD
        if state.get("strict"):
            system += prompts.STRICT_ADD
        user = prompts.ANSWER_USER.format(sources=source_list(hits, web_sources), question=state["question"])
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
        hits = state["hits"]
        web_sources = state.get("web_sources", [])
        # статьи из официальных веб-страниц (например КоАП) тоже считаются подтверждёнными
        tool_text += "\n" + "\n".join(w["text"] for w in web_sources if w["trust"] in ("official", "authority"))
        text, cited, invalid, used = check_citations(state["answer"], hits, tool_text, len(web_sources))
        sources = []
        for n in used:
            if n <= len(hits):
                h = hits[n - 1]
                sources.append({"n": n, "citation": h.citation, "law": h.law, "article": h.article, "trust": "local",
                                "snippet": h.text[:200].replace("\n", " ")})
            else:
                w = web_sources[n - len(hits) - 1]
                sources.append({"n": n, "citation": w["title"], "law": "web", "article": "", "trust": w["trust"],
                                "url": w["url"], "date": w.get("date"), "snippet": w["text"][:200].replace("\n", " ")})
        unverified = unverified_cited(text, len(hits), web_sources)
        update = {"answer": text, "sources": sources, "cited": cited, "invalid": invalid, "again": False,
                  "unverified_cited": unverified}
        if unverified:
            update["warning"] = "В ответе есть ссылка на непроверенный сайт, это не официальный источник."
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
    g.add_node("web", web)
    g.add_node("refuse", refuse)
    g.add_node("answer", answer)
    g.add_node("verify", verify)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["retrieve", "answer", "web", "refuse"])
    g.add_conditional_edges("web", after_web, ["answer", "refuse"])
    g.add_edge("refuse", END)
    g.add_edge("answer", "verify")
    g.add_conditional_edges("verify", after_verify, {"answer": "answer", "end": END})
    return g.compile()
