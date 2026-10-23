from dataclasses import dataclass
from functools import lru_cache

from .bm25 import BM25Index
from .embed import embed
from .store import COLLECTION, citation, get_client, load_units

RRF_K = 60
# bm25 на бытовых формулировках заметно слабее векторов, поэтому вес меньше
WEIGHTS = (1.0, 0.3)


@dataclass
class Hit:
    law: str
    article: str
    part: str
    title: str
    text: str
    score: float
    citation: str


@lru_cache(maxsize=1)
def units_by_id():
    return {u["id"]: u for u in load_units()}


@lru_cache(maxsize=1)
def bm25_index():
    return BM25Index(load_units())


def make_hit(unit, score):
    return Hit(
        law=unit["law"],
        article=unit["article"],
        part=unit["part"],
        title=unit["title"],
        text=unit["text"],
        score=score,
        citation=citation(unit["law"], unit["article"]),
    )


def vector_search(query, k):
    vec = embed([query])[0]
    res = get_client().query_points(COLLECTION, query=vec, limit=k, with_payload=True)
    return [(p.payload["id"], p.score) for p in res.points]


def bm25_search(query, k):
    return bm25_index().search(query, k)


def rrf(rankings, k, weights=WEIGHTS):
    """rankings - списки (id, score) от разных поисковиков, уже отсортированные"""
    total = {}
    for ranking, w in zip(rankings, weights):
        for pos, (uid, _) in enumerate(ranking):
            total[uid] = total.get(uid, 0) + w / (RRF_K + pos + 1)
    return sorted(total.items(), key=lambda x: x[1], reverse=True)[:k]


def search(query, k=8):
    pool = max(k * 4, 30)
    fused = rrf([vector_search(query, pool), bm25_search(query, pool)], k)
    by_id = units_by_id()
    # TODO: реранкер (bge-reranker) поверх fused, когда будет время
    return [make_hit(by_id[uid], score) for uid, score in fused]


def get_article(law, article):
    """Вся статья целиком (части склеиваются). None, если такой нет."""
    parts = [u for u in load_units() if u["law"] == law and u["article"] == str(article)]
    if not parts:
        return None
    text = "\n".join(u["text"] for u in parts)
    return make_hit({**parts[0], "part": "", "text": text}, 1.0)
