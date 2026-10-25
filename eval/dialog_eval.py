"""Оценка многоходовых диалогов: ход-продолжение не уходит в отказ, ответ короткий, есть уточняющие вопросы.
Запуск: uv run python eval/dialog_eval.py --limit 3"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.agent.chat import Chat  # noqa: E402
from pravoved.agent.dialog import answer_stats  # noqa: E402
from pravoved.agent.run import make_agent  # noqa: E402
from pravoved.retrieval.store import close_client  # noqa: E402

CASES = ROOT / "eval" / "dialog_cases.jsonl"
RESULTS = ROOT / "eval" / "results"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_turn(turn, res):
    """Список провалов одного хода по ожиданиям из кейса."""
    stats = answer_stats(res["answer"])
    fails = []
    if turn.get("refuse"):
        if not res["refused"]:
            fails.append("нужен отказ, а его нет")
        return fails
    if res["refused"]:
        fails.append("отказ")
        return fails
    if stats["words"] > turn.get("words_max", 220):
        fails.append("длинный ответ: %d слов" % stats["words"])
    if turn.get("clarify") and not (stats["clarify"] and stats["questions"] >= 1):
        fails.append("нет уточняющих вопросов")
    if stats["cites"] == 0:
        fails.append("нет ссылок")
    return fails


async def run_case(chat, case):
    turns = []
    for turn in case["turns"]:
        res = await chat.turn(turn["user"])
        fails = check_turn(turn, res)
        print("  [%s] %s" % ("ok" if not fails else "; ".join(fails), turn["user"][:60]))
        turns.append({"user": turn["user"], "rewritten": res["question"], "answer": res["answer"],
                      "refused": res["refused"], "seconds": res["seconds"],
                      "stats": answer_stats(res["answer"]), "fails": fails})
    return {"id": case["id"], "turns": turns}


async def main(limit):
    graph = await make_agent()
    results = []
    for case in load(CASES)[:limit or None]:
        print(case["id"])
        results.append(await run_case(Chat(graph), case))
    close_client()
    turns = [t for r in results for t in r["turns"]]
    followups = [t for r in results for t in r["turns"][1:]]
    summary = {
        "turns": len(turns),
        "turns_ok": sum(not t["fails"] for t in turns),
        "followup_refused": sum(t["refused"] for t in followups),
        "avg_words": round(sum(t["stats"]["words"] for t in turns) / len(turns)),
    }
    print(json.dumps(summary, ensure_ascii=False))
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "dialog-eval.json"
    out.write_text(json.dumps({"summary": summary, "cases": results}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    asyncio.run(main(p.parse_args().limit))
