"""Оценка ответов агента целиком (она же бенчмарк моделей).
Запуск: uv run python eval/answer_eval.py --tag qwen3.5-4b --limit 15"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.agent.run import ask, make_agent  # noqa: E402
from pravoved.retrieval.store import close_client  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
TOOL_CASES = ROOT / "eval" / "tool_cases.jsonl"
RESULTS = ROOT / "eval" / "results"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pick(items, limit):
    # равномерная выборка, чтобы в короткий прогон попали и вопросы вне базы (они в конце файла)
    if not limit or limit >= len(items):
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def cited_keys(res):
    return {"%s:%s" % (s["law"], s["article"]) for s in res["sources"]}


def args_match(expected, got):
    for key, want in expected.items():
        if key == "days" and "days" not in got and got.get("start_date") and got.get("end_date"):
            have = (date.fromisoformat(got["end_date"]) - date.fromisoformat(got["start_date"])).days
        else:
            have = got.get(key)
        if isinstance(want, (int, float)):
            try:
                if abs(float(have) - want) > 0.01:
                    return False
            except (TypeError, ValueError):
                return False
        elif have != want:
            return False
    return True


def check_tool_case(case, res):
    calls = [c for c in res["tool_calls"] if c["name"] == case["tool"]]
    return {"tool_ok": bool(calls), "args_ok": bool(calls) and args_match(case["args"], calls[0]["args"])}


async def run_all(graph, items, kind):
    out = []
    for i, item in enumerate(items, 1):
        print("[%s %d/%d] %s" % (kind, i, len(items), item["question"][:70]), flush=True)
        try:
            res = await ask(graph, item["question"])
        except Exception as e:
            print("  ошибка:", e)
            res = {"error": str(e), "answer": "", "refused": False, "sources": [], "tool_calls": [],
                   "cited": 0, "invalid": 0, "seconds": 0, "tokens_per_sec": None}
        res["case"] = item
        out.append(res)
    return out


def metrics(q_runs, t_runs):
    m = {}
    ok = [r for r in q_runs if "error" not in r]
    in_scope = [r for r in ok if r["case"]["expected"]]
    answered = [r for r in in_scope if not r["refused"]]
    out_scope = [r for r in ok if not r["case"]["expected"]]
    cited = sum(r["cited"] for r in answered)
    if answered:
        m["citation_precision"] = round((cited - sum(r["invalid"] for r in answered)) / cited, 3) if cited else None
        m["invalid_per_answer"] = mean([r["invalid"] for r in answered])
        m["no_citation_answers"] = sum(1 for r in answered if not r["sources"])
        hits = [[e in cited_keys(r) for e in r["case"]["expected"]] for r in answered]
        m["expected_hit_any"] = mean([any(h) for h in hits])
        m["expected_recall"] = mean([sum(h) / len(h) for h in hits])
    if in_scope:
        m["false_refusal_rate"] = mean([r["refused"] for r in in_scope])
    if out_scope:
        m["refusal_on_out_of_scope"] = mean([r["refused"] for r in out_scope])
    checks = [check_tool_case(r["case"], r) for r in t_runs if "error" not in r]
    if checks:
        m["tool_selection_acc"] = mean([c["tool_ok"] for c in checks])
        m["tool_args_acc"] = mean([c["args_ok"] for c in checks])
    allr = ok + [r for r in t_runs if "error" not in r]
    m["avg_latency_s"] = mean([r["seconds"] for r in allr])
    m["avg_tokens_per_sec"] = mean([r["tokens_per_sec"] for r in allr if r.get("tokens_per_sec")])
    m["errors"] = len(q_runs) + len(t_runs) - len(allr)
    m["n_questions"] = len(q_runs)
    m["n_tool_cases"] = len(t_runs)
    return m


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="сохранить результат в eval/results/TAG.json")
    parser.add_argument("--limit", type=int, help="сколько вопросов из questions.jsonl взять")
    parser.add_argument("--skip-questions", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    args = parser.parse_args()

    graph = await make_agent()
    start = time.time()
    q_runs = [] if args.skip_questions else await run_all(graph, pick(load(QUESTIONS), args.limit), "q")
    t_runs = [] if args.skip_tools else await run_all(graph, load(TOOL_CASES), "tool")
    m = metrics(q_runs, t_runs)
    for key, value in m.items():
        print("%-25s %s" % (key, value))

    if args.tag:
        RESULTS.mkdir(exist_ok=True)
        data = {"tag": args.tag, "model": os.environ.get("LLM_MODEL"), "date": date.today().isoformat(),
                "total_seconds": round(time.time() - start), "metrics": m, "questions": q_runs, "tool_cases": t_runs}
        with open(RESULTS / (args.tag + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    try:
        asyncio.run(main())
    finally:
        close_client()
