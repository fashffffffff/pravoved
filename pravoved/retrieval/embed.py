import os
from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")


def pick_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def get_model():
    model = SentenceTransformer(EMBED_MODEL, device=pick_device())
    model.max_seq_length = 512
    return model


def embed(texts, batch_size=16):
    vecs = get_model().encode(
        texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=len(texts) > 50
    )
    return vecs.tolist()


def unit_text(unit):
    # заголовок статьи в начало - так эмбеддинг лучше ловит тему
    return unit["title"] + ". " + unit["text"]
