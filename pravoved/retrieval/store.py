import json
import os
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "chunks.jsonl"
QDRANT_PATH = ROOT / "data" / "index" / "qdrant"
COLLECTION = "pravoved"

LAW_NAMES = {
    "zozpp": "ЗоЗПП",
    "tk": "ТК РФ",
    "gk": "ГК РФ",
    "plenum17": "Пленум ВС №17",
    "koap": "КоАП РФ",
    "pp657": "Правила продажи (ПП №657)",
    "pp924": "Перечень технически сложных товаров (ПП №924)",
}

# перечни целиком, без номера пункта
LISTS = {
    ("pp657", "remont"): "перечень товаров длительного пользования",
    ("pp657", "obmen"): "перечень товаров, не подлежащих обмену",
}


def load_units():
    with open(CHUNKS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@lru_cache(maxsize=1)
def get_client():
    # если задан QDRANT_URL - ходим на сервер, иначе встроенный режим в папке data/index
    # читаем при вызове, а не при импорте: .env может загрузиться позже
    url = os.environ.get("QDRANT_URL")
    if url:
        return QdrantClient(url=url)
    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_PATH))


def citation(law, article):
    name = LAW_NAMES.get(law, law)
    if law == "pp924":
        return name
    if (law, article) in LISTS:
        return "%s, %s" % (name, LISTS[(law, article)])
    if law in ("plenum17", "pp657"):
        return "%s, п. %s" % (name, article)
    return "%s, ст. %s" % (name, article)


def close_client():
    # закрываем сами, иначе при выходе qdrant ругается в __del__
    if get_client.cache_info().currsize:
        get_client().close()
        get_client.cache_clear()
