from types import SimpleNamespace

from pravoved.agent.situation import filter_hits
from pravoved.corpus.sections import section_of


def hit(regime):
    return SimpleNamespace(regime=regime, citation=regime)


def test_prokat_dropped_for_office_rent():
    hits = [hit("arenda_obshchaya"), hit("prokat"), hit("naem_zhilya"), hit("arenda_zdanij")]
    kept, dropped = filter_hits(hits, "arenda_nezhilogo")
    assert [h.regime for h in kept] == ["arenda_obshchaya", "arenda_zdanij"]
    assert [h.regime for h in dropped] == ["prokat", "naem_zhilya"]


def test_sever_only_when_asked():
    hits = [hit("trud_sever"), hit(""), hit("trud_osobyj")]
    assert [h.regime for h in filter_hits(hits, "trud")[0]] == [""]
    assert len(filter_hits(hits, "trud_sever")[0]) == 3


def test_goods_and_services_are_demoted_not_dropped():
    hits = [hit("potrebitel_usluga"), hit("potrebitel_tovar"), hit("")]
    kept, dropped = filter_hits(hits, "potrebitel_tovar")
    assert [h.regime for h in kept] == ["potrebitel_tovar", "", "potrebitel_usluga"]
    assert dropped == []


def test_unknown_situation_changes_nothing():
    hits = [hit("prokat"), hit("trud_sever")]
    assert filter_hits(hits, "")[0] == hits
    assert filter_hits(hits, "drugoe")[0] == hits


def test_keeps_everything_if_all_dropped():
    hits = [hit("prokat")]
    assert filter_hits(hits, "naem_zhilya") == (hits, [])


def test_sections():
    assert section_of("gk", "629") == ("ГК, гл. 34 §2 Прокат", "prokat")
    assert section_of("gk", "610")[1] == "arenda_obshchaya"
    assert section_of("tk", "318")[1] == "trud_sever"
    assert section_of("tk", "312.1")[1] == "trud_osobyj"
    assert section_of("tk", "236")[1] == ""
    assert section_of("pp657", "obmen") == ("", "")
