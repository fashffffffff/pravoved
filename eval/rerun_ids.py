"""Перепрогон вопросов, которые судья не признал верными (или любых id из командной строки).
Запуск: uv run python eval/rerun_ids.py --tag rerun1 [q10 q26 tool7]"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.agent.run import ask, make_agent  # noqa: E402
from pravoved.retrieval.store import close_client  # noqa: E402

RESULTS = ROOT / "eval" / "results"
JUDGE = RESULTS / "judge-final-gemma4.json"


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def find_case(case_id, questions, tools):
    # q10 - вопрос номер 10 из questions.jsonl, tool3 - задача номер 3 из tool_cases.jsonl
    kind, num = ("tool", int(case_id[4:])) if case_id.startswith("tool") else ("q", int(case_id[1:]))
    for c in (tools if kind == "tool" else questions):
        if c["id"] == num:
            return c
    raise SystemExit("нет такого id: " + case_id)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="по умолчанию все не-correct из judge-final-gemma4.json")
    parser.add_argument("--tag", default="rerun")
    args = parser.parse_args()

    ids = args.ids
    if not ids:
        judge = json.loads(JUDGE.read_text(encoding="utf-8"))
        ids = [i["id"] for i in judge["items"] if i["verdict"] != "correct"]
    questions, tools = load(ROOT / "eval" / "questions.jsonl"), load(ROOT / "eval" / "tool_cases.jsonl")

    graph = await make_agent()
    out = []
    for case_id in ids:
        case = find_case(case_id, questions, tools)
        print("[%s] %s" % (case_id, case["question"][:70]), flush=True)
        res = await ask(graph, case["question"])
        res["case_id"] = case_id
        out.append(res)
        print(res["answer"], "\n", flush=True)
    path = RESULTS / (args.tag + ".json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("сохранено:", path)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    try:
        asyncio.run(main())
    finally:
        close_client()
