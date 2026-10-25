import json

import pytest

from pravoved.corpus.parse import build_refs, edge_type, expand_numbers, find_refs, make_unit
from pravoved.retrieval import graph, search


def test_ranges_expand():
    assert expand_numbers("8 - 12") == ["8", "9", "10", "11", "12"]
    assert expand_numbers("20, 21, 22") == ["20", "21", "22"]
    assert expand_numbers("22.1 - 22.3") == ["22.1", "22.3"]


def test_plenum_refs():
    text = "об ответственности (статья 13), о возмещении вреда (статья 14), статьями 8 - 10 Закона"
    assert find_refs("plenum17", text) == [("zozpp", "13"), ("zozpp", "14"), ("zozpp", "8"), ("zozpp", "9"), ("zozpp", "10")]
    assert find_refs("plenum17", "статьи 15 ГК РФ и статьи 135 ГПК РФ") == [("gk", "15")]
    # гражданский процессуальный кодекс - не ГК
    assert find_refs("plenum17", "статьи 22 Гражданского процессуального кодекса") == []


def test_tk_internal():
    assert find_refs("tk", "в порядке, предусмотренном статьей 236 настоящего Кодекса") == [("tk", "236")]


def test_edge_types_and_links():
    assert edge_type("plenum17", "zozpp") == "explains"
    assert edge_type("plenum17", "gk") == "explains"
    assert edge_type("zozpp", "zozpp") == "refers_to"
    units = [
        make_unit("plenum17", "28", "", "", "по статье 18 Закона о защите прав потребителей"),
        make_unit("zozpp", "18", "", "", "см. статью 19 настоящего Закона"),
        make_unit("zozpp", "19", "", "", "текст"),
        make_unit("zozpp", "25", "", "", "текст"),
        make_unit("pp657", "obmen", "", "", "перечень"),
    ]
    edges = build_refs(units)
    assert ("plenum17:28", "zozpp:18", "explains") in edges
    assert ("zozpp:18", "zozpp:19", "refers_to") in edges
    assert ("zozpp:25", "pp657:obmen", "refers_to") in edges   # ссылка из списка LINKS
    assert all(b != "pp924:perechen" for _, b, _ in edges)     # такой статьи в корпусе нет


@pytest.fixture
def small_graph(tmp_path, monkeypatch):
    rows = [
        {"from": "plenum17:28", "to": "zozpp:18", "type": "explains"},
        {"from": "plenum17:29", "to": "zozpp:18", "type": "explains"},
        {"from": "zozpp:18", "to": "zozpp:19", "type": "refers_to"},
        {"from": "zozpp:20", "to": "zozpp:18", "type": "refers_to"},
        {"from": "zozpp:19", "to": "zozpp:21", "type": "refers_to"},
    ]
    path = tmp_path / "refs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(graph, "REFS", path)
    graph.load_graph.cache_clear()
    yield
    graph.load_graph.cache_clear()


def test_neighbors_both_directions_plenum_first(small_graph):
    nb = graph.neighbors("zozpp", "18")
    assert [(n["law"], n["article"]) for n in nb] == [
        ("plenum17", "28"), ("plenum17", "29"), ("zozpp", "20"), ("zozpp", "19")]
    assert nb[0]["type"] == "explains" and nb[0]["direction"] == "in"
    assert nb[-1]["direction"] == "out"
    assert graph.neighbors("zozpp", "999") == []


def test_expand_skips_known_and_limits(small_graph):
    got = graph.expand(["zozpp:18"], skip={"zozpp:19"})
    assert [n for n, _ in got] == ["plenum17:28", "plenum17:29", "zozpp:20"]
    assert got[0][1] == "граф: ЗоЗПП, ст. 18 → Пленум ВС №17, п. 28"
    assert len(graph.expand(["zozpp:18"], skip=set(), limit=2)) == 2
    assert len(graph.expand(["zozpp:18"], skip=set(), per_seed=1)) == 1


def test_expand_plenum_has_priority_over_earlier_seed(small_graph):
    # у первого семени только обычная ссылка, у второго - пленум; при лимите 1 побеждает пленум
    got = graph.expand(["zozpp:19", "zozpp:18"], skip={"zozpp:19", "zozpp:18"}, limit=1)
    assert got[0][0] == "plenum17:28"


def test_graph_enabled_env(monkeypatch):
    monkeypatch.setenv("GRAPH_EXPAND", "false")
    assert not graph.graph_enabled()
    monkeypatch.setenv("GRAPH_EXPAND", "true")
    assert graph.graph_enabled()


def test_graph_candidates_adds_all_parts(small_graph, monkeypatch):
    by_article = {
        "plenum17:28": [{"id": "plenum17:28"}],
        "zozpp:20": [{"id": "zozpp:20:1"}, {"id": "zozpp:20:2"}],
    }
    monkeypatch.setattr(search, "units_by_article", lambda: by_article)
    extra = search.graph_candidates(["zozpp:18:1", "zozpp:18:2", "zozpp:19"])
    assert "plenum17:28" in extra and "zozpp:20:1" in extra and "zozpp:20:2" in extra
    assert extra["plenum17:28"].startswith("граф: ЗоЗПП, ст. 18")
    assert not any(uid.startswith("zozpp:19") for uid in extra)
