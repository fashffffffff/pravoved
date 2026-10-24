from pravoved.retrieval import search as s


def test_rerank_env(monkeypatch):
    monkeypatch.delenv("RERANK", raising=False)
    assert s.rerank_enabled()
    monkeypatch.setenv("RERANK", "false")
    assert not s.rerank_enabled()


def test_rerank_orders_by_score(monkeypatch):
    class Fake:
        def predict(self, pairs, **kwargs):
            return [len(text) for _, text in pairs]

    monkeypatch.setattr(s, "reranker", lambda: Fake())
    monkeypatch.setattr(s, "units_by_id", lambda: {
        "a": {"title": "a", "text": "коротко"},
        "b": {"title": "b", "text": "значительно длиннее"},
    })
    assert [uid for uid, _ in s.rerank("вопрос", ["a", "b"])] == ["b", "a"]
