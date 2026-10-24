import json
from datetime import date

from pravoved.corpus import meta


def test_corpus_date_is_earliest(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({
        "a": {"downloaded": "2026-10-24", "edition": "ред. от 01.01.2026"},
        "b": {"downloaded": "2026-10-20", "edition": ""},
    }))
    monkeypatch.setattr(meta, "META", path)
    assert meta.corpus_date() == date(2026, 10, 20)
    assert meta.editions() == {"a": "ред. от 01.01.2026", "b": ""}


def test_corpus_date_without_file(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "META", tmp_path / "none.json")
    assert meta.corpus_date() is None
