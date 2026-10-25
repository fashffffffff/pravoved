"""Оценка поиска: recall@5, recall@8 и MRR для vector, bm25, hybrid, hybrid+rerank и hybrid+graph+rerank.
Попадание считаем по статье (law:article), части одной статьи не различаем.
Отдельно считаем вопросы, где ожидается две и больше статей (там граф должен помогать).
  -v        вопросы, где графу есть что сказать
  --sweep   перебор GRAPH_TOP / PER_SEED / GRAPH_MAX"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pravoved.retrieval.graph import GRAPH_MAX, GRAPH_TOP, PER_SEED  # noqa: E402
from pravoved.retrieval.search import (  # noqa: E402
    RERANK_POOL, bm25_search, graph_candidates, rerank, rrf, units_by_id, vector_search,
)
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


def rerank_cached(query, ids, cache):
    """реранкер считает каждую пару один раз, чтобы перебор настроек был быстрым"""
    missing = [uid for uid in ids if uid not in cache]
    if missing:
        t = time.time()
        cache.update(rerank(query, missing))
        rerank_times.append(time.time() - t)
    return sorted(((uid, cache[uid]) for uid in ids), key=lambda x: x[1], reverse=True)


def with_graph(query, hybrid, cache, params):
    ids = [uid for uid, _ in hybrid[:RERANK_POOL]]
    extra = graph_candidates(ids, *params)
    top = rerank_cached(query, ids + list(extra), cache)
    return unique_articles(top + hybrid[RERANK_POOL:]), extra


def rank_all(query, params):
    vec = vector_search(query, POOL)
    bm = bm25_search(query, POOL)
    hybrid = rrf([vec, bm], POOL)
    cache = {}
    top = rerank_cached(query, [uid for uid, _ in hybrid[:RERANK_POOL]], cache)
    graph, extra = with_graph(query, hybrid, cache, params)
    return {
        "vector": unique_articles(vec),
        "bm25": unique_articles(bm),
        "hybrid": unique_articles(hybrid),
        "hybrid+rerank": unique_articles(top + hybrid[RERANK_POOL:]),
        "hybrid+graph+rerank": graph,
    }, hybrid, cache, extra


def recall_at(found, expected, k):
    hit = [a for a in expected if a in found[:k]]
    return len(hit) / len(expected)


def mrr(found, expected):
    for i, a in enumerate(found, 1):
        if a in expected:
            return 1 / i
    return 0


def table(title, questions, ranked, names):
    print("\n%s: %d вопросов" % (title, len(questions)))
    print("%-20s %9s %9s %7s" % ("", "recall@5", "recall@8", "MRR"))
    for n in names:
        r5 = [recall_at(ranked[q["id"]][n], q["expected"], 5) for q in questions]
        r8 = [recall_at(ranked[q["id"]][n], q["expected"], 8) for q in questions]
        m = [mrr(ranked[q["id"]][n], q["expected"]) for q in questions]
        print("%-20s %9.3f %9.3f %7.3f" % (n, sum(r5) / len(r5), sum(r8) / len(r8), sum(m) / len(m)))


def sweep(questions, hybrids, caches):
    print("\nперебор (top, всего, на семя): recall@5 / recall@8 / MRR, все вопросы | вопросы с 2+ статьями recall@8")
    multi = [q for q in questions if len(q["expected"]) >= 2]
    for params in [(0, 0, 0), (3, 6, 3), (3, 10, 4), (5, 8, 3), (5, 10, 4), (5, 15, 5), (8, 12, 4), (8, 20, 4)]:
        ranked = {}
        for q in questions:
            if params[0] == 0:
                ids = [uid for uid, _ in hybrids[q["id"]][:RERANK_POOL]]
                top = rerank_cached(q["question"], ids, caches[q["id"]])
                ranked[q["id"]] = unique_articles(top + hybrids[q["id"]][RERANK_POOL:])
            else:
                ranked[q["id"]] = with_graph(q["question"], hybrids[q["id"]], caches[q["id"]], params)[0]
        r5 = sum(recall_at(ranked[q["id"]], q["expected"], 5) for q in questions) / len(questions)
        r8 = sum(recall_at(ranked[q["id"]], q["expected"], 8) for q in questions) / len(questions)
        m = sum(mrr(ranked[q["id"]], q["expected"]) for q in questions) / len(questions)
        r8m = sum(recall_at(ranked[q["id"]], q["expected"], 8) for q in multi) / len(multi)
        print("%-12s %.3f / %.3f / %.3f | %.3f" % (params, r5, r8, m, r8m))


def main():
    questions = [q for q in load_questions() if q["expected"]]
    names = ["vector", "bm25", "hybrid", "hybrid+rerank", "hybrid+graph+rerank"]
    ranked, hybrids, caches, extras = {}, {}, {}, {}
    for q in questions:
        ranked[q["id"]], hybrids[q["id"]], caches[q["id"]], extras[q["id"]] = rank_all(q["question"], (GRAPH_TOP, GRAPH_MAX, PER_SEED))

    print("GRAPH_TOP=%d PER_SEED=%d GRAPH_MAX=%d" % (GRAPH_TOP, PER_SEED, GRAPH_MAX))
    table("все вопросы с ответом", questions, ranked, names)
    multi = [q for q in questions if len(q["expected"]) >= 2]
    table("ожидается 2+ статьи", multi, ranked, names)
    print("rerank на запрос: %.2f с в среднем (с графом кандидатов больше)" % (sum(rerank_times) / len(questions)))

    if "--sweep" in sys.argv:
        sweep(questions, hybrids, caches)

    if "-v" in sys.argv:
        print("\nчто граф принёс из ожидаемого:")
        by_id = units_by_id()
        for q in questions:
            base, graph = ranked[q["id"]]["hybrid+rerank"][:8], ranked[q["id"]]["hybrid+graph+rerank"][:8]
            new = [a for a in q["expected"] if a in graph and a not in base]
            lost = [a for a in q["expected"] if a in base and a not in graph]
            if new or lost:
                vias = {article_of(uid): v for uid, v in extras[q["id"]].items()}
                print("#%d %s\n   добавил %s, потерял %s" % (q["id"], q["question"], new, lost))
                for a in new:
                    print("   %s <- %s" % (a, vias.get(a)))
    close_client()


if __name__ == "__main__":
    main()
