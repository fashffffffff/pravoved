import os
from dataclasses import dataclass
from functools import lru_cache

from .bm25 import BM25Index
from .embed import embed, pick_device, unit_text
from .store import COLLECTION, citation, get_client, load_units

RRF_K = 60
# bm25 на бытовых формулировках заметно слабее векторов, поэтому вес меньше
WEIGHTS = (1.0, 0.3)
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_POOL = 20


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


def rerank_enabled():
    return os.environ.get("RERANK", "true").strip().lower() not in ("0", "false", "no", "off")


@lru_cache(maxsize=1)
def reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANK_MODEL, device=pick_device(), max_length=512)


def rerank(query, ids):
    """Переупорядочивает кандидатов кросс-энкодером. -> список (id, score) по убыванию"""
    by_id = units_by_id()
    pairs = [(query, unit_text(by_id[uid])) for uid in ids]
    scores = reranker().predict(pairs, batch_size=8, show_progress_bar=False)
    return sorted(zip(ids, (float(x) for x in scores)), key=lambda x: x[1], reverse=True)


def search(query, k=8):
    pool = max(k * 4, 30)
    by_id = units_by_id()
    if rerank_enabled():
        fused = rrf([vector_search(query, pool), bm25_search(query, pool)], max(RERANK_POOL, k))
        ranked = rerank(query, [uid for uid, _ in fused])[:k]
    else:
        ranked = rrf([vector_search(query, pool), bm25_search(query, pool)], k)
    return [make_hit(by_id[uid], score) for uid, score in ranked]


def get_article(law, article):
    """Вся статья целиком (части склеиваются). None, если такой нет."""
    parts = [u for u in load_units() if u["law"] == law and u["article"] == str(article)]
    if not parts:
        return None
    text = "\n".join(u["text"] for u in parts)
    return make_hit({**parts[0], "part": "", "text": text}, 1.0)
