"""Оценка проверки договоров на синтетических договорах из eval/contract_cases.
Запуск: uv run python eval/contract_eval.py --tag gemma4"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.agent import run  # noqa: E402
from pravoved.retrieval.store import close_client  # noqa: E402

CASES = ROOT / "eval" / "contract_cases"
RESULTS = ROOT / "eval" / "results"
COLORS = ("red", "yellow", "green")


def parse_labels(text):
    """Строки 'id цвет [law:article|law:article]'. -> {id: {"color": ..., "articles": set}}"""
    labels = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] not in COLORS:
            raise ValueError("плохая строка разметки: " + line)
        articles = set()
        if len(parts) > 2 and parts[2] != "-":
            articles = set(parts[2].split("|"))
        labels[parts[0]] = {"color": parts[1], "articles": articles}
    return labels


def score(labels, clauses):
    """clauses - результат проверки (список пунктов с color и cites)"""
    got = {c["id"]: c for c in clauses}
    found = [i for i in labels if i in got]
    tp = sum(labels[i]["color"] == "red" and got[i]["color"] == "red" for i in found)
    pred_red = sum(got[i]["color"] == "red" for i in found)
    true_red = sum(labels[i]["color"] == "red" for i in found)
    same = sum(labels[i]["color"] == got[i]["color"] for i in found)
    # статья засчитывается, если среди найденных есть любая из ожидаемых
    with_article = [i for i in found if labels[i]["color"] == "red" and labels[i]["articles"]]
    article_ok = sum(bool(labels[i]["articles"] & {"%s:%s" % (c["law"], c["article"]) for c in got[i]["cites"]})
                     for i in with_article)
    return {
        "clauses": len(found), "missing_ids": [i for i in labels if i not in got],
        "red_tp": tp, "red_pred": pred_red, "red_true": true_red,
        "agree": same, "article_ok": article_ok, "article_total": len(with_article),
        "wrong": [(i, labels[i]["color"], got[i]["color"]) for i in found if labels[i]["color"] != got[i]["color"]],
    }


def ratio(a, b):
    return round(a / b, 3) if b else None


def totals(scores):
    s = {k: sum(x[k] for x in scores) for k in ("clauses", "red_tp", "red_pred", "red_true", "agree", "article_ok", "article_total")}
    return {"red_recall": ratio(s["red_tp"], s["red_true"]), "red_precision": ratio(s["red_tp"], s["red_pred"]),
            "color_agreement": ratio(s["agree"], s["clauses"]), "article_match": ratio(s["article_ok"], s["article_total"]), **s}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="run")
    parser.add_argument("--cases", nargs="*", help="имена договоров без расширения")
    args = parser.parse_args()
    names = args.cases or sorted(p.stem for p in CASES.glob("*.txt"))
    await run.make_agent()
    out, scores = [], []
    for name in names:
        text = (CASES / (name + ".txt")).read_text(encoding="utf-8")
        labels = parse_labels((CASES / (name + ".labels")).read_text(encoding="utf-8"))
        print("[%s]" % name, flush=True)
        res = await run.check_contract_text(text, name)
        s = score(labels, res["clauses"])
        scores.append(s)
        out.append({"name": name, "seconds": res["seconds"], "invalid_refs": res["invalid"], **s})
        print("  %.1f с, red %d/%d (предсказано %d), цвета совпали %d/%d, ссылок неверных %d"
              % (res["seconds"], s["red_tp"], s["red_true"], s["red_pred"], s["agree"], s["clauses"], res["invalid"]))
        for i, want, have in s["wrong"]:
            print("    %s: ожидали %s, получили %s" % (i, want, have))
        if s["missing_ids"]:
            print("    пункты не найдены при разбиении:", s["missing_ids"])
    total = totals(scores)
    total["invalid_refs"] = sum(o["invalid_refs"] for o in out)
    total["seconds_per_contract"] = round(sum(o["seconds"] for o in out) / len(out), 1)
    print(json.dumps(total, ensure_ascii=False, indent=1))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / ("contract-%s.json" % args.tag)).write_text(
        json.dumps({"total": total, "contracts": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    close_client()


if __name__ == "__main__":
    asyncio.run(main())
