import json
import os
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "chunks.jsonl"
QDRANT_PATH = ROOT / "data" / "index" / "qdrant"
COLLECTION = "pravoved"

# если задан QDRANT_URL - ходим на сервер, иначе встроенный режим в папке data/index
QDRANT_URL = os.environ.get("QDRANT_URL")

LAW_NAMES = {
    "zozpp": "ЗоЗПП",
    "tk": "ТК РФ",
    "gk": "ГК РФ",
    "plenum17": "Пленум ВС №17",
}


def load_units():
    with open(CHUNKS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@lru_cache(maxsize=1)
def get_client():
    if QDRANT_URL:
        return QdrantClient(url=QDRANT_URL)
    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_PATH))


def citation(law, article):
    name = LAW_NAMES.get(law, law)
    if law == "plenum17":
        return "%s, п. %s" % (name, article)
    return "%s, ст. %s" % (name, article)


def close_client():
    # закрываем сами, иначе при выходе qdrant ругается в __del__
    get_client().close()
    get_client.cache_clear()
