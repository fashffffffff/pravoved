"""Грубая автоматическая оценка прогона без LLM: попадание в нужные статьи, покрытие must_mention, отказы.
Запуск: uv run python eval/judge_lite.py dev-final [--questions eval/dev.jsonl] [--show]"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.agent.verify import norm_num, word_numbers  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def squeeze(text):
    # "5 000" -> "5000", ё -> е
    text = text.lower().replace("ё", "е")
    return re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)


def numbers(text):
    found = {norm_num(x) for x in re.findall(r"\d+(?:[.,]\d+)?", squeeze(text))}
    return found | word_numbers(text)


def stems(text):
    return {w[:5] for w in re.findall(r"[a-zа-я]{3,}", squeeze(text))}


def mentioned(item, answer):
    """Все числа из пункта есть в ответе и не меньше 60% слов (по первым 5 буквам)."""
    nums = numbers(item)
    if nums and not nums <= numbers(answer):
        return False
    words = stems(re.sub(r"\d+", " ", item))
    if not words:
        return True
    return len(words & stems(answer)) / len(words) >= 0.6


def article_hit(res, expected):
    got = {"%s:%s" % (s["law"], s["article"]) for s in res["sources"]}
    return [e in got for e in expected]


def evaluate(run, questions):
    rows = []
    for res in run["questions"]:
        case = res["case"]
        # must_mention и reference берём из файла вопросов, если их нет в прогоне
        extra = questions.get(case["question"], {})
        must = case.get("must_mention") or extra.get("must_mention") or []
        answer = res.get("answer", "")
        hits = article_hit(res, case["expected"]) if case["expected"] else []
        covered = [mentioned(m, answer) for m in must]
        rows.append({"id": case.get("id"), "question": case["question"], "refused": res.get("refused", False),
                     "error": "error" in res, "hit_any": any(hits) if hits else None,
                     "hit_all": all(hits) if hits else None,
                     "cover": sum(covered) / len(covered) if covered else None,
                     "full": all(covered) if covered else None, "missing": [m for m, c in zip(must, covered) if not c],
                     "seconds": res.get("seconds", 0)})
    return rows


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summary(rows):
    in_scope = [r for r in rows if r["hit_any"] is not None]
    return {"n": len(rows), "hit_any": avg([r["hit_any"] for r in in_scope]), "hit_all": avg([r["hit_all"] for r in in_scope]),
            "must_cover": avg([r["cover"] for r in rows]), "must_full": avg([r["full"] for r in rows]),
            "refused": sum(r["refused"] for r in rows), "errors": sum(r["error"] for r in rows),
            "seconds": avg([r["seconds"] for r in rows])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "dev.jsonl")
    parser.add_argument("--show", action="store_true", help="показать пропущенные пункты")
    args = parser.parse_args()
    with open(RESULTS / (args.tag + ".json"), encoding="utf-8") as f:
        run = json.load(f)
    questions = {}
    if args.questions.exists():
        with open(args.questions, encoding="utf-8") as f:
            questions = {q["question"]: q for q in map(json.loads, filter(str.strip, f))}
    rows = evaluate(run, questions)
    s = summary(rows)
    print(json.dumps(s, ensure_ascii=False))
    if args.show:
        for r in rows:
            if r["missing"]:
                print("%s %s\n   нет: %s" % (r["id"], r["question"][:70], "; ".join(r["missing"])))


if __name__ == "__main__":
    main()
