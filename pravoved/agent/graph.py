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
from pravoved.agent.tools import DOC_TOOLS, WEB_TOOLS
from pravoved.agent.verify import check_citations, only_unverified, strip_unverified, unbacked_numbers, unverified_cited
from pravoved.corpus.meta import corpus_date
from pravoved.mcp_server.web import TRUST_ORDER
from pravoved.retrieval.search import search

MAX_RETRIES = 2
MAX_SOURCES = 10
MAX_TOOL_STEPS = 5
SNIPPET = 1500
WEB_SNIPPET = 3500
MAX_WEB_PAGES = 3
MAX_WEB_TRIES = 5
SITES = " site:consultant.ru OR site:pravo.gov.ru OR site:garant.ru"
# если среди результатов нет ни одного надёжного сайта, ищем ещё раз только по официальным
SITES_ALL = (" site:consultant.ru OR site:garant.ru OR site:pravo.gov.ru OR site:rospotrebnadzor.ru"
             " OR site:rostrud.gov.ru")
# вопросы про расчёты отвечают инструменты, а не поиск; маленькие модели в grade часто путают их с вопросами вне базы
CALC_WORDS = re.compile(r"ключев\w* ставк|неустойк|до какого числа|какого числа|когда (?:истека|законч)|компенсаци\w* за задержк", re.IGNORECASE)
# деньги + сроки/даты + просьба посчитать: считать должен инструмент
QUESTION_MONEY = re.compile(r"\d\s*(?:₽|руб|р\.|тыс)", re.IGNORECASE)
QUESTION_TIME = re.compile(r"\d+\s*(?:дн|календарн|рабоч|недел|месяц)|\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)|\d{1,2}\.\d{2}\.\d{4}", re.IGNORECASE)
QUESTION_ASK = re.compile(r"сколько|посчита|рассчита|подсчита|размер", re.IGNORECASE)
# уголовное право вне базы, веб для него не нужен: отказываем сразу
CRIMINAL_WORDS = re.compile(r"уголовн|\bУК\b|кражу|краже|убийств|преступлен|мошенничеств", re.IGNORECASE)
# вопросы про свежие изменения и штрафы: локальная база их не знает, идём в интернет
WEB_WORDS = re.compile(r"нов\w+ закон|(?:с|в) (?:\d+ \w+ )?20[2-9]\d|измени[лт]\w*|изменени\w*|\bсейчас\b|штраф|коап|принят\w* ли|законопроект", re.IGNORECASE)


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
    unbacked_numbers: int
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


def needs_calc(question):
    if CALC_WORDS.search(question):
        return True
    return bool(QUESTION_MONEY.search(question) and QUESTION_TIME.search(question) and QUESTION_ASK.search(question))


def tool_result_text(result):
    if isinstance(result, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


def verify(state):
    tool_text = "\n".join(c["result"] for c in state["tool_calls"])
    hits = state["hits"]
    web_sources = state.get("web_sources", [])
    answer = state["answer"]
    # были надёжные источники, а модель сослалась на непроверенный: убираем эти ссылки
    unverified = unverified_cited(answer, len(hits), web_sources)
    if unverified and (hits or any(w["trust"] != "unverified" for w in web_sources)):
        answer = strip_unverified(answer, len(hits), web_sources)
    # статьи из официальных веб-страниц (например КоАП) тоже считаются подтверждёнными
    tool_text += "\n" + "\n".join(w["text"] for w in web_sources if w["trust"] in ("official", "authority"))
    text, cited, invalid, used = check_citations(answer, hits, tool_text, len(web_sources))
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
    if not sources and not state["tool_calls"] and not state.get("regenerated"):
        return {"strict": True, "regenerated": True, "again": True}
    warnings = []
    if not sources and not state["tool_calls"]:
        warnings.append("В ответе нет подтверждённых ссылок на источники, проверьте его самостоятельно.")
    if only_unverified(sources) or (not sources and only_unverified(web_sources)):
        text = prompts.UNVERIFIED_TOP + "\n\n" + text
    elif unverified_cited(text, len(hits), web_sources):
        warnings.append("В ответе есть ссылка на непроверенный сайт, это не официальный источник.")
    # сегодняшняя дата есть в системном промпте
    backing = [state["question"], tool_text, date.today().strftime("%d.%m.%Y")] + [hits[n - 1].text for n in used if n <= len(hits)]
    backing += [web_sources[n - len(hits) - 1]["text"] for n in used if n > len(hits)]
    unbacked = unbacked_numbers(text, "\n".join(backing))
    if unbacked:
        warnings.append("Проверьте цифры: " + ", ".join(unbacked) + " - их нет в источниках и расчётах.")
    update = {"answer": text, "sources": sources, "cited": cited, "invalid": invalid, "again": False,
              "unverified_cited": unverified, "unbacked_numbers": len(unbacked)}
    if warnings:
        update["warning"] = "\n".join(warnings)
    return update


def build_graph(llm, tools):
    tools_by_name = {t.name: t for t in tools}
    answer_tools = [t for t in tools if t.name not in WEB_TOOLS | DOC_TOOLS]
    llm_tools = llm.bind_tools(answer_tools) if answer_tools else llm
    llm_forced = llm.bind_tools(answer_tools, tool_choice="required") if answer_tools else None
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
        elif CRIMINAL_WORDS.search(state["question"]):
            out, enough, legal = True, False, False
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

    async def read_pages(candidates, question):
        pages = []
        for r in candidates:
            if len(pages) == MAX_WEB_PAGES:
                break
            page = await call_json("read_page", {"url": r["url"]})
            if not page.get("text"):
                continue
            pages.append({"url": r["url"], "title": page.get("title") or r["title"], "trust": r["trust"],
                          "date": page.get("date"), "text": relevant_part(page["text"], question, WEB_SNIPPET)})
        return pages

    async def web(state):
        question = state["question"]
        queries, usage = await web_queries(question)
        # плюс вариант с официальными сайтами - поисковик часто ставит их выше
        found = {}
        for q in queries + [queries[0] + SITES]:
            for r in (await call_json("web_search", {"query": q, "max_results": 6})).get("results", []):
                found.setdefault(r["url"], r)
        if all(r["trust"] == "unverified" for r in found.values()):
            for r in (await call_json("web_search", {"query": queries[0] + SITES_ALL, "max_results": 6})).get("results", []):
                found.setdefault(r["url"], r)
        ranked = sorted(found.values(), key=lambda r: TRUST_ORDER.index(r["trust"]))
        good = [r for r in ranked if r["trust"] != "unverified"]
        # сначала пробуем прочитать надёжные страницы (часть может не открыться)
        pages = await read_pages(good[:MAX_WEB_TRIES], question)
        if not pages:
            # надёжных нет совсем: непроверенные идут в ответ с предупреждением
            pages = await read_pages([r for r in ranked if r["trust"] == "unverified"][:MAX_WEB_PAGES], question)
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
        base = corpus_date()
        base_date = prompts.BASE_DATE.format(date=base.strftime("%d.%m.%Y")) if base else ""
        system = prompts.ANSWER_SYSTEM.format(today=date.today().strftime("%d.%m.%Y"), base_date=base_date)
        if web_sources and all(w["trust"] == "unverified" for w in web_sources):
            system += prompts.WEB_ADD + prompts.WEB_UNVERIFIED_ADD
        elif web_sources:
            system += prompts.WEB_ADD
        if state.get("strict"):
            system += prompts.STRICT_ADD
        user = prompts.ANSWER_USER.format(sources=source_list(hits, web_sources), question=state["question"])
        msgs = [SystemMessage(system), HumanMessage(user)]
        force = needs_calc(state["question"])
        text, calls, usage = await tool_loop(list(msgs), force)
        if not calls:
            # в ответе есть цифры, которых нет в источниках и вопросе, а инструмент не вызывали
            backing = state["question"] + "\n" + source_list(hits, web_sources)
            if unbacked_numbers(text, backing):
                text2, calls2, usage2 = await tool_loop(msgs + [HumanMessage(prompts.CALC_NUDGE)], True)
                usage += usage2
                if calls2:
                    text, calls = text2, calls2
        return {"answer": text, "tool_calls": calls, "usage": usage}

    async def tool_loop(msgs, force):
        calls = []
        usage = []
        text = ""
        for step in range(MAX_TOOL_STEPS):
            t = time.time()
            msg = await call_llm(msgs, force and step == 0)
            usage.append(usage_of(msg, time.time() - t))
            msgs.append(msg)
            text = strip_think(msg.content if isinstance(msg.content, str) else "")
            if not msg.tool_calls:
                break
            for call in msg.tool_calls:
                result = await run_tool(call)
                calls.append({"name": call["name"], "args": call["args"], "result": result})
                msgs.append(ToolMessage(content=result, tool_call_id=call["id"]))
        return text, calls, usage

    async def call_llm(msgs, force):
        if force and llm_forced:
            try:
                return await llm_forced.ainvoke(msgs)
            except Exception:
                # сервер не поддерживает tool_choice, работаем как обычно
                pass
        return await llm_tools.ainvoke(msgs)

    async def run_tool(call):
        tool = tools_by_name.get(call["name"])
        if tool is None:
            return "Ошибка: нет инструмента " + call["name"]
        try:
            return tool_result_text(await tool.ainvoke(call["args"]))
        except Exception as e:
            # ошибку отдаём модели, пусть исправит аргументы
            return "Ошибка инструмента: %s" % e

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
