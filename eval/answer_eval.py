"""Оценка ответов агента целиком (она же бенчмарк моделей).
Запуск: uv run python eval/answer_eval.py --tag qwen3.5-4b --limit 15"""
import argparse
import asyncio
import json
import os
import re
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
WEB_CASES = ROOT / "eval" / "web_cases.jsonl"
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


def normalize_args(args):
    # одно и то же можно передать днями или датами, kind у своего срока можно не указывать
    args = dict(args)
    due, actual = args.pop("due_date", None), args.pop("actual_date", None)
    if "days" not in args and due and actual:
        args["days"] = (date.fromisoformat(actual) - date.fromisoformat(due)).days
    if "event_date" in args and "kind" not in args:
        args["kind"] = "custom"
    return args


def args_match(expected, got):
    expected, got = normalize_args(expected), normalize_args(got)
    for key, want in expected.items():
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
                   "cited": 0, "invalid": 0, "seconds": 0, "tokens_per_sec": None,
                   "unverified_cited": 0, "unbacked_numbers": 0, "web_used": False}
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
        m["unbacked_numbers_per_answer"] = mean([r.get("unbacked_numbers", 0) for r in answered])
        hits = [[e in cited_keys(r) for e in r["case"]["expected"]] for r in answered]
        m["expected_hit_any"] = mean([any(h) for h in hits])
        m["expected_recall"] = mean([sum(h) / len(h) for h in hits])
    if in_scope:
        m["false_refusal_rate"] = mean([r["refused"] for r in in_scope])
    # вне базы: нужно отказать (не право, уголовное) или можно ответить по официальным сайтам (web_ok)
    must_refuse = [r for r in out_scope if r["case"].get("expect", "refuse") == "refuse"]
    web_ok = [r for r in out_scope if r["case"].get("expect") == "web_ok"]
    if must_refuse:
        m["refusal_on_out_of_scope"] = mean([r["refused"] for r in must_refuse])
    if web_ok:
        m["web_ok_answered"] = mean([not r["refused"] for r in web_ok])
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


def web_metrics(runs):
    ok = [r for r in runs if "error" not in r]
    m = {"n_web_cases": len(runs), "errors": len(runs) - len(ok)}
    if not ok:
        return m
    m["web_used_share"] = mean([r["web_used"] for r in ok])
    m["refused_share"] = mean([r["refused"] for r in ok])
    # основа ответа надёжная: есть ссылка на официальный/авторитетный/локальный источник и нет ссылок на unverified
    trusted = [any(s["trust"] in ("local", "official", "authority") for s in r["sources"]) and not r["unverified_cited"]
               for r in ok if not r["refused"]]
    m["trusted_basis_share"] = mean(trusted)
    m["unverified_cited"] = sum(r["unverified_cited"] for r in ok)
    m["draft_cited"] = sum(1 for r in ok for s in r["sources"] if s["trust"] == "draft")
    # у приманки в кейсе есть регулярка с ложным утверждением: смотрим, повторил ли его ответ
    bait = [r for r in ok if r["case"].get("fake")]
    m["fake_repeated"] = sum(1 for r in bait if re.search(r["case"]["fake"], r["answer"]))
    m["avg_latency_s"] = mean([r["seconds"] for r in ok])
    return m


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="сохранить результат в eval/results/TAG.json")
    parser.add_argument("--limit", type=int, help="сколько вопросов из questions.jsonl взять")
    parser.add_argument("--skip-questions", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    parser.add_argument("--web", action="store_true", help="только вопросы из web_cases.jsonl (нужен интернет)")
    args = parser.parse_args()

    graph = await make_agent()
    start = time.time()
    if args.web:
        q_runs = await run_all(graph, load(WEB_CASES), "web")
        t_runs = []
        m = web_metrics(q_runs)
    else:
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
