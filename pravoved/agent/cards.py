"""Памятки по частым темам (data/cards/*.md): что обязательно проверить и сказать.
Памятка - подсказка для модели, не источник. Статьи из неё добавляются в источники, чтобы на них можно было сослаться."""
import re
from functools import lru_cache
from pathlib import Path

from pravoved.agent.situation import SITUATIONS
from pravoved.retrieval.search import make_hit, units_by_article, units_by_id

CARDS = Path(__file__).resolve().parents[2] / "data" / "cards"
MAX_CARDS = 2


def split_list(text):
    return [s.strip() for s in text.split(",") if s.strip()]


@lru_cache(maxsize=1)
def load_cards():
    cards = []
    for path in sorted(CARDS.glob("*.md")):
        head, _, body = path.read_text(encoding="utf-8").partition("\n---\n")
        meta = dict(line.split(": ", 1) for line in head.splitlines()[1:] if ": " in line)
        cards.append({
            "name": path.stem,
            "title": meta.get("title", path.stem),
            "when": re.compile(meta["when"], re.IGNORECASE),
            "sources": split_list(meta.get("sources", "")),
            "situations": split_list(meta.get("situations", "")),
            "text": body.strip(),
        })
    return cards


def pick_cards(question, situation="", limit=MAX_CARDS):
    """Карточки, в которых сработало больше всего слов-признаков; если ситуация известна, чужие карточки пропускаем"""
    scored = []
    for card in load_cards():
        if situation in SITUATIONS and situation != "drugoe" and card["situations"] and situation not in card["situations"]:
            continue
        n = len(card["when"].findall(question))
        if n:
            scored.append((n, card))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]


def card_units(card):
    by_id, by_article = units_by_id(), units_by_article()
    units = []
    for ref in card["sources"]:
        if ref in by_id:
            units.append(by_id[ref])
        else:
            units += by_article.get(ref, [])
    return units


def card_hits(cards):
    return [make_hit(u, 1.0, "памятка") for card in cards for u in card_units(card)]
