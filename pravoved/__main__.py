import argparse
import asyncio
import os

from rich.console import Console
from rich.markdown import Markdown

from pravoved.agent.run import ask, make_agent
from pravoved.corpus.meta import corpus_date
from pravoved.retrieval.store import close_client

console = Console()
BADGE_COLORS = {"official": "green", "authority": "green", "draft": "yellow", "unverified": "red"}


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


async def run(args):
    if args.debug:
        os.environ["PRAVOVED_DEBUG"] = "1"
    graph = await make_agent()
    on_step = show_step if args.debug else None
    if args.cmd == "ask":
        show_result(await ask(graph, args.question, on_step))
        return
    console.print("Правовед. Пустая строка или Ctrl-D - выход.")
    while True:
        try:
            question = input("\nВопрос> ").strip()
        except EOFError:
            break
        if not question:
            break
        show_result(await ask(graph, question, on_step))


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="показывать шаги графа")
    parser = argparse.ArgumentParser(prog="pravoved")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ask", parents=[common]).add_argument("question")
    sub.add_parser("chat", parents=[common])
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    finally:
        close_client()


main()
