import argparse
import asyncio
import os

from rich.console import Console
from pathlib import Path

from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from pravoved.agent import run as agent_run
from pravoved.agent.chat import Chat
from pravoved.agent.contract import COLORS, read_file
from pravoved.agent.run import ask, make_agent
from pravoved.corpus.meta import corpus_date
from pravoved.retrieval.store import close_client

console = Console()
BADGE_COLORS = {"official": "green", "authority": "green", "draft": "yellow", "unverified": "red"}
CLAUSE_COLORS = {"red": "red", "yellow": "yellow", "green": "green"}
KIND_NAMES = {"rent": "найм жилья", "labour": "трудовой договор", "consumer": "договор с потребителем"}


def show_step(node, update):
    if node == "retrieve":
        console.print("[dim]retrieve: найдено %d источников[/dim]" % len(update["hits"]))
    elif node == "grade":
        console.print("[dim]grade: enough=%s out_of_scope=%s retry=%s[/dim]"
                      % (update["enough"], update["out_of_scope"], update["retry"]))
        if update["retry"]:
            console.print("[dim]  новый запрос: %s[/dim]" % update["queries"][-1])
    elif node == "web":
        for w in update["web_sources"]:
            console.print("[dim]web: %s %s[/dim]" % (w["trust"], w["url"]))
        if not update["web_sources"]:
            console.print("[dim]web: ничего не нашли[/dim]")
    elif node == "answer":
        for c in update["tool_calls"]:
            console.print("[dim]tool: %s %s -> %s[/dim]" % (c["name"], c["args"], c["result"][:100].replace("\n", " ")))
    elif node == "verify":
        if update.get("again"):
            console.print("[dim]verify: нет верных ссылок, пробуем ещё раз строже[/dim]")
        else:
            console.print("[dim]verify: ссылок %d, неверных %d[/dim]" % (update["cited"], update["invalid"]))
    else:
        console.print("[dim]%s[/dim]" % node)


def show_result(res):
    console.print()
    console.print(Markdown(res["answer"]))
    if res["warning"]:
        console.print("[yellow]%s[/yellow]" % res["warning"])
    if res["sources"]:
        console.print("\n[bold]Источники:[/bold]")
        for s in res["sources"]:
            if s["trust"] == "local":
                console.print("[%d] [cyan]%s[/cyan] - %s..." % (s["n"], s["citation"], s["snippet"][:120]), highlight=False)
            else:
                color = BADGE_COLORS[s["trust"]]
                console.print("[%d] [%s]\\[%s][/%s] %s %s, дата: %s" % (s["n"], color, s["trust"], color, s["citation"][:80], s["url"], s.get("date") or "не указана"), highlight=False)
    if res["tool_calls"]:
        console.print("\n[bold]Вызовы инструментов:[/bold]")
        for c in res["tool_calls"]:
            console.print("%s %s" % (c["name"], c["args"]), highlight=False)
    console.print("[dim]%.1f с, %s ток/с[/dim]" % (res["seconds"], res["tokens_per_sec"]))
    base = corpus_date()
    if base:
        console.print("[dim]База: законы по состоянию на %s[/dim]" % base.strftime("%d.%m.%Y"))


def show_progress(i, n):
    console.print("[dim]проверяю пункты, часть %d из %d...[/dim]" % (i, n))


def short(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def show_contract(res):
    console.print()
    table = Table(show_lines=True)
    table.add_column("№")
    table.add_column("")
    table.add_column("Пункт", max_width=45)
    table.add_column("Что не так", max_width=50)
    table.add_column("Статьи", max_width=26)
    for r in res["clauses"]:
        if r["color"] == "green":
            continue
        cites = "\n".join(c["citation"] for c in r["cites"])
        table.add_row(r["id"], COLORS[r["color"]], Text(short(r["text"], 160)), Text(r["reason"], style=CLAUSE_COLORS[r["color"]]), cites)
    if table.row_count:
        console.print(table)
    c = res["counts"]
    console.print("\n[bold]Итого[/bold] (%s): 🔴 %d  🟡 %d  🟢 %d, всего пунктов %d"
                  % (KIND_NAMES[res["kind"]], c["red"], c["yellow"], c["green"], len(res["clauses"])))
    if res["top_risks"]:
        console.print("\n[bold]Главные риски:[/bold]")
        for r in res["top_risks"]:
            console.print("🔴 п. %s: %s" % (r["id"], r["reason"]), highlight=False)
    console.print("[dim]%.1f с[/dim]" % res["seconds"])


def show_chat_reply(reply):
    if reply["kind"] == "answer":
        show_result(reply)
    elif reply["kind"] == "contract":
        show_contract(reply["result"])
    else:
        console.print()
        console.print(reply["text"], highlight=False)


async def run(args):
    if args.debug:
        os.environ["PRAVOVED_DEBUG"] = "1"
    graph = await make_agent()
    on_step = show_step if args.debug else None
    if args.cmd == "ask":
        show_result(await ask(graph, args.question, on_step))
        return
    if args.cmd == "check":
        text = await read_file(Path(args.file).expanduser(), agent_run.kit["tools"])
        show_contract(await agent_run.check_contract_text(text, args.file, show_progress))
        return
    chat = Chat(graph)
    console.print("Правовед. Пустая строка или Ctrl-D - выход.")
    while True:
        try:
            question = input("\nВопрос> ").strip()
        except EOFError:
            break
        if not question:
            break
        show_chat_reply(await chat.turn(question, on_step, show_progress))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="показывать шаги графа")
    parser = argparse.ArgumentParser(prog="pravoved")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ask", parents=[common]).add_argument("question")
    sub.add_parser("check", parents=[common]).add_argument("file", help="договор: txt, docx, pdf или скан (jpg, png)")
    sub.add_parser("chat", parents=[common])
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    finally:
        close_client()


main()
