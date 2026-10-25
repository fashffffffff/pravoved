import asyncio
import os
import sys
import threading
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pravoved.agent import run as agent_run  # noqa: E402
from pravoved.corpus.meta import corpus_date  # noqa: E402

BADGES = {
    "local": ("локальная база", "#2f6f4f"),
    "official": ("официальный", "#2f6f4f"),
    "authority": ("ведомство", "#2b6a8f"),
    "draft": ("законопроект", "#a8741a"),
    "unverified": ("непроверенный", "#a63d3d"),
}
STEP_NAMES = {
    "retrieve": "ищу в базе законов",
    "grade": "проверяю, хватает ли найденного",
    "web": "ищу в интернете",
    "answer": "пишу ответ",
    "verify": "проверяю ссылки",
}
CSS = """
<style>
.badge {display:inline-block; padding:1px 8px; border-radius:10px; color:#fff; font-size:0.75rem; margin-right:6px;}
.src {margin:0.35rem 0; font-size:0.92rem;}
.via {color:#777; font-size:0.85rem;}
.refusal {border-left:4px solid #a8741a; padding:0.4rem 0.9rem; background:rgba(168,116,26,0.08); border-radius:4px;}
</style>
"""


# граф и MCP-клиент привязаны к своему event loop, поэтому крутим его в отдельном потоке
@st.cache_resource
def get_backend():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    graph = asyncio.run_coroutine_threadsafe(agent_run.make_agent(), loop).result()
    return loop, graph


def run_question(question, status):
    loop, graph = get_backend()
    steps = []

    def on_step(node, update):
        steps.append(node)

    fut = asyncio.run_coroutine_threadsafe(agent_run.ask(graph, question, on_step), loop)
    shown = 0
    while True:
        try:
            return fut.result(timeout=0.5)
        except TimeoutError:
            if len(steps) != shown:
                shown = len(steps)
                status.update(label="Шаг: %s..." % STEP_NAMES.get(steps[-1], steps[-1]))


def call_in_loop(coro):
    loop, _ = get_backend()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def badge(trust):
    label, color = BADGES.get(trust, (trust, "#777"))
    return '<span class="badge" style="background:%s">%s</span>' % (color, label)


def show_sources(sources):
    if not sources:
        return
    st.markdown("**Источники**")
    for s in sources:
        line = "[%s] %s %s" % (s["n"], badge(s["trust"]), s["citation"])
        if s.get("url"):
            line += ' <a href="%s">%s</a>' % (s["url"], s["url"])
        if s.get("date"):
            line += " (дата: %s)" % s["date"]
        if s.get("via"):
            line += '<div class="via">через граф: %s</div>' % s["via"]
        st.markdown('<div class="src">%s</div>' % line, unsafe_allow_html=True)


def tool_files(res):
    for c in res.get("tool_calls", []):
        text = str(c.get("result", ""))
        for ext in (".docx", ".ics"):
            if ext in text:
                # результат инструмента - json с полем path, но на всякий случай ищем и в тексте
                path = find_path(text, ext)
                if path:
                    yield path


def find_path(text, ext):
    import json
    try:
        data = json.loads(text)
        if isinstance(data, dict) and str(data.get("path", "")).endswith(ext):
            return data["path"]
    except ValueError:
        pass
    for word in text.replace('"', " ").replace(",", " ").split():
        if word.endswith(ext) and os.path.exists(word):
            return word
    return None


def show_downloads(res, key):
    seen = set()
    for i, path in enumerate(tool_files(res)):
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        with open(path, "rb") as f:
            st.download_button("Скачать " + os.path.basename(path), f.read(),
                               file_name=os.path.basename(path), key="%s-dl-%d" % (key, i))


def show_tools(res, debug):
    calls = res.get("tool_calls", [])
    if not calls and not debug:
        return
    with st.expander("Вызовы инструментов (%d)" % len(calls)):
        for c in calls:
            st.markdown("`%s`" % c["name"])
            st.json(c["args"], expanded=False)
            st.code(str(c["result"])[:1500], language=None)
        if debug:
            st.caption("запросы к базе: %s" % "; ".join(res.get("queries", [])))
            st.caption("ссылок: %s, неверных: %s, веб: %s" % (res.get("cited"), res.get("invalid"), res.get("web_used")))


def show_warnings(res):
    if res.get("warning"):
        st.warning(res["warning"])
    if res.get("unverified_cited"):
        st.warning("В ответе есть ссылки на непроверенные источники: %d." % res["unverified_cited"])
    if res.get("unbacked_numbers"):
        st.warning("Проверьте цифры: %d чисел в ответе не подтверждены расчётом или источником." % res["unbacked_numbers"])


def show_answer(res, key, debug):
    if res.get("refused"):
        st.markdown('<div class="refusal">%s</div>' % res["answer"], unsafe_allow_html=True)
    else:
        st.markdown(res["answer"])
    show_warnings(res)
    show_sources(res.get("sources"))
    show_downloads(res, key)
    show_tools(res, debug)
    tps = res.get("tokens_per_sec")
    st.caption("%.1f с%s" % (res.get("seconds", 0), ", %s ток/с" % tps if tps else ""))


def sidebar():
    st.sidebar.title("Правовед")
    base = corpus_date()
    if base:
        st.sidebar.caption("Законы по состоянию на %s" % base.strftime("%d.%m.%Y"))
    st.sidebar.caption("Модель: %s" % os.environ.get("LLM_MODEL", "local"))
    web = st.sidebar.toggle("Поиск в интернете", value=True)
    os.environ["WEB_ENABLED"] = "true" if web else "false"
    debug = st.sidebar.toggle("Показывать шаги (debug)", value=False)
    st.sidebar.divider()
    contract_panel()
    scan_panel()
    st.sidebar.divider()
    if st.sidebar.button("Очистить чат"):
        st.session_state.messages = []
        st.rerun()
    return debug


def contract_panel():
    with st.sidebar.expander("Проверить договор"):
        check = getattr(agent_run, "check_contract", None)
        if check is None:
            st.caption("Скоро.")
            return
        up = st.file_uploader("Договор", type=["txt", "docx", "pdf", "jpg", "png"], key="contract")
        if up and st.button("Проверить", key="contract_go"):
            with st.spinner("Проверяю договор..."):
                st.session_state.contract = call_in_loop(check(*contract_args(up)))


def contract_args(up):
    _, graph = get_backend()
    return graph, up.name, up.getvalue()


def scan_panel():
    with st.sidebar.expander("Распознать скан"):
        read = getattr(agent_run, "read_scan", None)
        if read is None:
            st.caption("Скоро.")
            return
        up = st.file_uploader("Скан", type=["jpg", "png", "pdf"], key="scan")
        if up and st.button("Распознать", key="scan_go"):
            with st.spinner("Распознаю..."):
                st.session_state.scan = call_in_loop(read(up.name, up.getvalue()))


def show_extra_results():
    if st.session_state.get("scan"):
        with st.expander("Распознанный текст", expanded=True):
            st.text(str(st.session_state.scan))
    if st.session_state.get("contract"):
        with st.expander("Проверка договора", expanded=True):
            st.markdown(str(st.session_state.contract))


def main():
    st.set_page_config(page_title="Правовед", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    debug = sidebar()
    st.title("Правовед")
    st.caption("Помощник по бытовому праву РФ. Отвечает со ссылками на статьи, а если не нашёл - так и говорит.")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    show_extra_results()

    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                show_answer(m["result"], "h%d" % i, debug)

    question = st.chat_input("Задайте вопрос по праву")
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.status("Думаю...", expanded=debug) as status:
            try:
                res = run_question(question, status)
            except Exception as e:
                status.update(label="Ошибка", state="error")
                st.error("Не получилось ответить: %s" % e)
                return
            status.update(label="Готово", state="complete")
        key = "h%d" % len(st.session_state.messages)
        show_answer(res, key, debug)
    st.session_state.messages.append({"role": "assistant", "result": res})


main()
