import os
from dataclasses import dataclass
from functools import lru_cache

from .bm25 import BM25Index
from .graph import GRAPH_MAX, GRAPH_TOP, PER_SEED, expand, graph_enabled
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
    via: str = ""   # почему попала в выдачу, если пришла из графа
    section: str = ""   # раздел кодекса, например "ГК, гл. 34 §2 Прокат"
    regime: str = ""    # код вида договора или особого режима для этого раздела


@lru_cache(maxsize=1)
def units_by_id():
    return {u["id"]: u for u in load_units()}


@lru_cache(maxsize=1)
def bm25_index():
    return BM25Index(load_units())


def make_hit(unit, score, via=""):
    return Hit(
        law=unit["law"],
        article=unit["article"],
        part=unit["part"],
        title=unit["title"],
        text=unit["text"],
        score=score,
        citation=citation(unit["law"], unit["article"]),
        via=via,
        section=unit.get("section", ""),
        regime=unit.get("regime", ""),
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


def article_key(uid):
    return ":".join(uid.split(":")[:2])


def graph_candidates(fused_ids, top=GRAPH_TOP, limit=GRAPH_MAX, per_seed=PER_SEED):
    """Соседи по графу для лучших результатов. -> {id единицы: via}.
    Берём все части статьи-соседа, выбирать среди них будет реранкер."""
    seeds = []
    for uid in fused_ids:
        key = article_key(uid)
        if key not in seeds:
            seeds.append(key)
    have = {article_key(uid) for uid in fused_ids[:RERANK_POOL]}
    extra = {}
    for node, via in expand(seeds[:top], have, limit, per_seed):
        for u in units_by_article().get(node, []):
            extra[u["id"]] = via
    return extra


@lru_cache(maxsize=1)
def units_by_article():
    result = {}
    for u in load_units():
        result.setdefault(u["law"] + ":" + u["article"], []).append(u)
    return result


def search(query, k=8):
    pool = max(k * 4, 30)
    by_id = units_by_id()
    via = {}
    if rerank_enabled():
        fused = rrf([vector_search(query, pool), bm25_search(query, pool)], max(RERANK_POOL, k))
        ids = [uid for uid, _ in fused]
        if graph_enabled():
            via = graph_candidates(ids)
        ranked = rerank(query, ids + list(via))[:k]
    else:
        ranked = rrf([vector_search(query, pool), bm25_search(query, pool)], k)
    return [make_hit(by_id[uid], score, via.get(uid, "")) for uid, score in ranked]


def get_article(law, article):
    """Вся статья целиком (части склеиваются). None, если такой нет."""
    parts = [u for u in load_units() if u["law"] == law and u["article"] == str(article)]
    if not parts:
        return None
    text = "\n".join(u["text"] for u in parts)
    return make_hit({**parts[0], "part": "", "text": text}, 1.0)
