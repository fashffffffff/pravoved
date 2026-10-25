import json
import os
from functools import lru_cache

from .store import ROOT, citation

REFS = ROOT / "data" / "refs.jsonl"

# сколько первых результатов берём как "семена", сколько соседей берём от одного семени и всего
GRAPH_TOP = 5
PER_SEED = 3
GRAPH_MAX = 8


def graph_enabled():
    return os.environ.get("GRAPH_EXPAND", "true").strip().lower() not in ("0", "false", "no", "off")


@lru_cache(maxsize=1)
def load_graph():
    """-> (исходящие, входящие): {"закон:статья": [("закон:статья", тип), ...]}"""
    out, inc = {}, {}
    if not REFS.exists():
        return out, inc
    with open(REFS, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            kind = e.get("type", "refers_to")
            out.setdefault(e["from"], []).append((e["to"], kind))
            inc.setdefault(e["to"], []).append((e["from"], kind))
    return out, inc


def neighbors(law, article):
    """Соседи статьи в обе стороны. -> список словарей law, article, type, direction,
    где direction: out (статья ссылается), in (на неё ссылаются).
    Сначала разъяснения Пленума, потом остальные входящие, потом исходящие."""
    node = "%s:%s" % (law, article)
    out, inc = load_graph()
    result = []
    for direction, edges in (("in", inc.get(node, [])), ("out", out.get(node, []))):
        for other, kind in edges:
            o_law, o_article = other.split(":", 1)
            result.append({"law": o_law, "article": o_article, "type": kind, "direction": direction})
    result.sort(key=lambda n: (n["type"] != "explains", n["direction"] != "in"))
    return result


def via_text(seed, n):
    """Почему статья попала в выдачу, для UI и ответа"""
    return "граф: %s → %s" % (citation(*seed.split(":", 1)), citation(n["law"], n["article"]))


def expand(seeds, skip, limit=GRAPH_MAX, per_seed=PER_SEED):
    """seeds - статьи ("закон:статья") лучших результатов по порядку, skip - статьи, которые уже есть.
    -> список (закон:статья, via). Разъяснения Пленума берём раньше остальных соседей."""
    seen = set(skip)
    found = []  # (пленум ли, номер семени, узел, via)
    for i, seed in enumerate(seeds):
        taken = 0
        for n in neighbors(*seed.split(":", 1)):
            node = "%s:%s" % (n["law"], n["article"])
            if node in seen or taken >= per_seed:
                continue
            seen.add(node)
            taken += 1
            found.append((n["type"] != "explains", i, node, via_text(seed, n)))
    found.sort(key=lambda x: x[:2])
    return [(node, via) for _, _, node, via in found[:limit]]
