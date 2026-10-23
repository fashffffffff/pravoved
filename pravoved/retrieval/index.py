from qdrant_client.models import Distance, PointStruct, VectorParams

from .embed import embed, unit_text
from .store import COLLECTION, close_client, get_client, load_units


def build(batch=64):
    units = load_units()
    client = get_client()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)

    first = embed([unit_text(units[0])])[0]
    client.create_collection(
        COLLECTION, vectors_config=VectorParams(size=len(first), distance=Distance.COSINE)
    )

    for start in range(0, len(units), batch):
        part = units[start:start + batch]
        vectors = embed([unit_text(u) for u in part])
        points = [
            PointStruct(id=start + i, vector=v, payload=u)
            for i, (u, v) in enumerate(zip(part, vectors))
        ]
        client.upsert(COLLECTION, points)
        print("%d / %d" % (min(start + batch, len(units)), len(units)), flush=True)
    close_client()
    print("готово, единиц:", len(units))
