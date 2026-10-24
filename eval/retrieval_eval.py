"""Оценка поиска: recall@5, recall@8 и MRR для vector, bm25, hybrid и hybrid+rerank.
Попадание считаем по статье (law:article), части одной статьи не различаем."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.retrieval.search import RERANK_POOL, bm25_search, rerank, rrf, vector_search  # noqa: E402
from pravoved.retrieval.store import close_client  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
POOL = 30
rerank_times = []


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def article_of(unit_id):
    law, article = unit_id.split(":")[:2]
    return law + ":" + article


def unique_articles(ranking):
    seen = []
    for uid, _ in ranking:
        a = article_of(uid)
        if a not in seen:
            seen.append(a)
    return seen


def rank_all(query):
    vec = vector_search(query, POOL)
    bm = bm25_search(query, POOL)
    hybrid = rrf([vec, bm], POOL)
    t = time.time()
    top = rerank(query, [uid for uid, _ in hybrid[:RERANK_POOL]])
    rerank_times.append(time.time() - t)
    return {
        "vector": unique_articles(vec),
        "bm25": unique_articles(bm),
        "hybrid": unique_articles(hybrid),
        "hybrid+rerank": unique_articles(top + hybrid[RERANK_POOL:]),
    }


def recall_at(found, expected, k):
    hit = [a for a in expected if a in found[:k]]
    return len(hit) / len(expected)


def mrr(found, expected):
    for i, a in enumerate(found, 1):
        if a in expected:
            return 1 / i
    return 0


def main():
    questions = [q for q in load_questions() if q["expected"]]
    names = ["vector", "bm25", "hybrid", "hybrid+rerank"]
    stats = {n: {"r5": [], "r8": [], "mrr": []} for n in names}
    misses = []

    for q in questions:
        ranked = rank_all(q["question"])
        for n in names:
            stats[n]["r5"].append(recall_at(ranked[n], q["expected"], 5))
            stats[n]["r8"].append(recall_at(ranked[n], q["expected"], 8))
            stats[n]["mrr"].append(mrr(ranked[n], q["expected"]))
        if recall_at(ranked["hybrid"], q["expected"], 8) < 1:
            misses.append((q, ranked["hybrid"][:8]))

    close_client()
    print("вопросов с ответом: %d" % len(questions))
    print("%-14s %9s %9s %7s" % ("", "recall@5", "recall@8", "MRR"))
    for n in names:
        avg = {k: sum(v) / len(v) for k, v in stats[n].items()}
        print("%-14s %9.3f %9.3f %7.3f" % (n, avg["r5"], avg["r8"], avg["mrr"]))

    print("rerank на запрос (%d кандидатов): %.2f с в среднем" % (RERANK_POOL, sum(rerank_times[1:]) / max(len(rerank_times) - 1, 1)))

    if "-v" in sys.argv:
        print("\nгде hybrid не нашёл всё в топ-8:")
        for q, top in misses:
            print("#%d %s\n   ждали %s, получили %s" % (q["id"], q["question"], q["expected"], top))


if __name__ == "__main__":
    main()
