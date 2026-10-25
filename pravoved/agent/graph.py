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
from pravoved.agent.cards import card_hits, pick_cards
from pravoved.agent.clean import drop_repeats, strip_marks
from pravoved.agent.faith import drop_markers, mismatch_reason, number_mismatch, pick_excerpt, plain, split_claims
from pravoved.agent.situation import describe, filter_hits
from pravoved.agent.tools import DOC_TOOLS, WEB_TOOLS
from pravoved.agent.verify import check_citations, only_unverified, strip_unverified, unbacked_numbers, unverified_cited
from pravoved.corpus.meta import corpus_date
from pravoved.mcp_server.web import TRUST_ORDER
from pravoved.retrieval.search import search

MAX_RETRIES = 2
MAX_SOURCES = 10
MAX_TOOL_STEPS = 5
MAX_CLAIMS = 15
SNIPPET = 1500
WEB_SNIPPET = 4500
MAX_WEB_PAGES = 3
MAX_WEB_TRIES = 5
SITES = " site:consultant.ru OR site:pravo.gov.ru OR site:garant.ru"
# практические страницы: порядок, сроки, документы
SITES_PRACTICAL = " site:consultant.ru OR site:garant.ru OR site:nalog.gov.ru OR site:gosuslugi.ru OR site:pravo.gov.ru"
# если среди результатов нет ни одного надёжного сайта, ищем ещё раз только по официальным
SITES_ALL = (" site:consultant.ru OR site:garant.ru OR site:pravo.gov.ru OR site:rospotrebnadzor.ru"
             " OR site:rostrud.gov.ru")
# вопросы про расчёты отвечают инструменты, а не поиск; маленькие модели в grade часто путают их с вопросами вне базы
CALC_WORDS = re.compile(r"ключев\w* ставк|неустойк|до какого числа|какого числа|когда (?:истека|законч)|компенсаци\w* за задержк", re.IGNORECASE)
# деньги + сроки/даты + просьба посчитать: считать должен инструмент
QUESTION_MONEY = re.compile(r"\d\s*(?:₽|руб|р\.|тыс)", re.IGNORECASE)
QUESTION_TIME = re.compile(r"\d+\s*(?:дн|календарн|рабоч|недел|месяц)|\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)|\d{1,2}\.\d{2}\.\d{4}", re.IGNORECASE)
QUESTION_ASK = re.compile(r"сколько|посчита|рассчита|подсчита|размер", re.IGNORECASE)
# модель отказывается отвечать, хотя инструмент вернул результат
GAVE_UP = re.compile(r"не могу (?:ответить|дать ответ|помочь)|невозможно ответить", re.IGNORECASE)
# уголовное право вне базы, веб для него не нужен: отказываем сразу
CRIMINAL_WORDS = re.compile(r"уголовн|\bУК\b|кражу|краже|убийств|преступлен|мошенничеств", re.IGNORECASE)
# вопросы про свежие изменения и штрафы: локальная база их не знает, идём в интернет
WEB_WORDS = re.compile(r"нов\w+ закон|(?:с|в) (?:\d+ \w+ )?20[2-9]\d|измени[лт]\w*|изменени\w*|\bсейчас\b|штраф|коап|принят\w* ли|законопроект", re.IGNORECASE)


class State(TypedDict, total=False):
    question: str
    history: str
    queries: list
    hits: list
    retries: int
    enough: bool
    retry: bool
    out_of_scope: bool
    legal: bool
    need_web: bool
    situation: str
    dropped: list
    cards: list
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
    faith_round: int
    faith_again: bool
    faith_feedback: str
    faith_seconds: float
    faith_issues: list
    claims_checked: int
    claims_unsupported: int
    claims_partial: int
    claims_fixed: int
    claims_unresolved: int
    usage: Annotated[list, operator.add]


def hit_key(h):
    return (h.law, h.article, h.part)


def format_source(i, h):
    part = ", ч. " + h.part if h.part else ""
    section = " (%s)" % h.section if h.section else ""
    return "[%d] %s%s. %s%s\n%s" % (i, h.citation, part, h.title, section, h.text[:SNIPPET])


def format_web_source(i, w):
    date_part = ", дата: " + w["date"] if w.get("date") else ""
    head = "[%d] ВЕБ, доверие: %s, %s%s" % (i, w["trust"], w["url"], date_part)
    return "%s\n%s\n<<<\n%s\n>>>" % (head, w["title"], w["text"])


def source_list(hits, web=()):
    parts = [format_source(i, h) for i, h in enumerate(hits, 1)]
    parts += [format_web_source(i, w) for i, w in enumerate(web, len(hits) + 1)]
    return "\n\n".join(parts)


def env_flag(name):
    return os.environ.get(name, "true").strip().lower() not in ("0", "false", "no", "off")


def web_enabled():
    return env_flag("WEB_ENABLED")


def faith_enabled():
    return env_flag("FAITH_CHECK")


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
    text, unconfirmed = strip_marks(text)
    text = drop_repeats(text)
    if unconfirmed:
        warnings.append("Не нашли в источниках: " + ", ".join(unconfirmed) + ". Эти упоминания проверьте сами.")
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
    faith_on = faith_enabled()

    def retrieve(state):
        query = state["queries"][-1]
        old = state.get("hits", [])
        seen = {hit_key(h) for h in old}
        new = [h for h in search(query, k=8) if hit_key(h) not in seen]
        new = filter_hits(new, state.get("situation", ""))[0]
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
        situation = str(data.get("situation") or "").strip()
        kept, dropped = filter_hits(hits, situation)
        update = {"enough": enough, "retry": False, "out_of_scope": out, "legal": legal, "need_web": need_web,
                  "where": str(data.get("where") or ""), "usage": usage, "situation": situation,
                  "hits": kept, "dropped": [h.citation for h in dropped]}
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
        for q in queries + [queries[0] + SITES_PRACTICAL]:
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
        cards = [] if state.get("out_of_scope") else pick_cards(state["question"], state.get("situation", ""))
        have = {hit_key(h) for h in hits}
        hits = hits + [h for h in card_hits(cards) if hit_key(h) not in have]
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
        for card in cards:
            user += prompts.CARD_ADD.format(title=card["title"], text=card["text"])
        if state.get("history"):
            user += prompts.HISTORY_ADD.format(history=state["history"])
        if state.get("faith_feedback"):
            user += "\n\n" + state["faith_feedback"]
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
        if calls and GAVE_UP.search(text):
            # инструмент ответил, а модель всё равно отказывается: просим ответить по его результату
            got = "\n".join("%s: %s" % (c["name"], c["result"]) for c in calls)
            text2, _, usage2 = await tool_loop(msgs + [HumanMessage(prompts.USE_TOOL_NUDGE.format(result=got))], False)
            usage += usage2
            if text2 and not GAVE_UP.search(text2):
                text = text2
        return {"answer": text, "tool_calls": calls, "usage": usage, "hits": hits, "cards": [c["name"] for c in cards]}

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
        if state["again"]:
            return "answer"
        return "faithfulness" if faith_on else "end"

    def after_faith(state):
        return "answer" if state["faith_again"] else "end"

    async def judge(pairs, question, tool_text, situation=""):
        # одним запросом: пары (утверждение, выдержка) -> {номер пары: (вердикт, причина)}
        known = prompts.FAITH_KNOWN.format(question=question, situation=situation or "не определена",
                                           calc=tool_text[:1500] or "нет")
        items = known + "\n\n".join("%d. Утверждение: %s\nИсточник: %s" % (i, claim, excerpt)
                                    for i, (claim, excerpt) in enumerate(pairs, 1))
        t = time.time()
        msg = await llm.ainvoke([SystemMessage(prompts.FAITH_SYSTEM), HumanMessage(items)])
        data = parse_json(strip_think(msg.content)) or {}
        verdicts = {}
        for v in data.get("verdicts", []):
            try:
                verdicts[int(v["id"])] = (str(v.get("verdict")), str(v.get("reason") or ""))
            except (KeyError, TypeError, ValueError):
                pass
        return verdicts, [usage_of(msg, time.time() - t)]

    async def faithfulness(state):
        start = time.time()
        hits = state["hits"]
        web_sources = state.get("web_sources", [])
        texts = {i: h.text for i, h in enumerate(hits, 1)}
        sections = {i: " (раздел: %s)" % h.section for i, h in enumerate(hits, 1) if h.section}
        texts.update({i: w["text"] for i, w in enumerate(web_sources, len(hits) + 1)})
        tool_text = "\n".join(c["result"] for c in state["tool_calls"])
        checked, to_ask = [], []
        for c in split_claims(state["answer"])[:MAX_CLAIMS]:
            cited = [n for n in dict.fromkeys(c["nums"]) if n in texts]
            if not cited:
                continue
            source = "\n".join(texts[n] for n in cited)
            c["excerpt"] = "\n".join("[%d]%s %s" % (n, sections.get(n, ""), pick_excerpt(texts[n], c["text"])) for n in cited)
            c["verdict"], c["reason"], c["by"] = "supported", "", "rules"
            problems = number_mismatch(c["text"], source + "\n" + tool_text + "\n" + state["question"])
            if problems:
                c["verdict"], c["reason"], c["by"] = "not_supported", mismatch_reason(problems), "numbers"
            else:
                to_ask.append(c)
            checked.append(c)
        usage = []
        if to_ask:
            verdicts, usage = await judge([(plain(c["text"]), c["excerpt"]) for c in to_ask],
                                       state["question"], tool_text, describe(state.get("situation", "")))
            for i, c in enumerate(to_ask, 1):
                verdict, reason = verdicts.get(i, ("supported", ""))
                if verdict in ("not_supported", "partially"):
                    c["verdict"], c["reason"], c["by"] = verdict, reason, "llm"
        bad = [c for c in checked if c["verdict"] == "not_supported"]
        partial = [c for c in checked if c["verdict"] == "partially"]
        seconds = state.get("faith_seconds", 0) + time.time() - start
        update = {"faith_seconds": round(seconds, 2), "faith_again": False, "usage": usage}
        if state.get("faith_round", 0) == 0:
            issues = [{"claim": plain(c["text"]), "reason": c["reason"], "by": c["by"], "excerpt": c["excerpt"]}
                      for c in bad + partial]
            update.update({"claims_checked": len(checked), "claims_unsupported": len(bad),
                           "claims_partial": len(partial), "claims_fixed": 0, "claims_unresolved": len(bad),
                           "faith_issues": issues})
            if bad:
                lines = ["- «%s» - %s. В источнике: %s" % (plain(c["text"]), c["reason"] or "нет в источнике", c["excerpt"])
                         for c in bad]
                update.update({"faith_round": 1, "faith_again": True,
                               "faith_feedback": prompts.FAITH_FEEDBACK.format(items="\n".join(lines))})
            return update
        # второй проход: что не исправилось, остаётся без ссылки и с предупреждением
        update["claims_fixed"] = max(0, state["claims_unsupported"] - len(bad))
        update["claims_unresolved"] = len(bad)
        if bad:
            text = drop_markers(state["answer"], bad)
            names = "; ".join(plain(c["text"])[:150] for c in bad)
            update["answer"] = text + "\n\n" + prompts.FAITH_WARNING + names
        return update

    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("web", web)
    g.add_node("refuse", refuse)
    g.add_node("answer", answer)
    g.add_node("verify", verify)
    g.add_node("faithfulness", faithfulness)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["retrieve", "answer", "web", "refuse"])
    g.add_conditional_edges("web", after_web, ["answer", "refuse"])
    g.add_edge("refuse", END)
    g.add_edge("answer", "verify")
    g.add_conditional_edges("verify", after_verify, {"answer": "answer", "faithfulness": "faithfulness", "end": END})
    g.add_conditional_edges("faithfulness", after_faith, {"answer": "answer", "end": END})
    return g.compile()
