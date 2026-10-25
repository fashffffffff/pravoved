from pravoved.agent.cards import card_units, load_cards, pick_cards
from pravoved.retrieval.search import units_by_id


def test_cards_have_sources_in_base():
    ids = units_by_id()
    for card in load_cards():
        assert card["when"].pattern and card["text"]
        assert card_units(card), card["name"]
        for ref in card["sources"]:
            assert ref in ids or any(u["id"].startswith(ref + ":") for u in ids.values()), ref


def test_card_text_mentions_only_its_sources():
    # статья в памятке должна быть среди источников этой же памятки, иначе на неё нельзя сослаться
    import re
    for card in load_cards():
        have = {u["article"] for u in card_units(card)}
        for num in re.findall(r"ст\. (\d+(?:\.\d+)*)", card["text"]):
            assert num in have, (card["name"], num)


def test_pick_by_words_and_situation():
    assert pick_cards("Задержали зарплату на месяц")[0]["name"] == "zarplata"
    assert [c["name"] for c in pick_cards("Съезжаю из арендованного офиса")] == ["arenda"]
    # чужая ситуация: памятка про аренду не подходит найму жилья
    assert "arenda" not in [c["name"] for c in pick_cards("Съезжаю из арендованной квартиры", "naem_zhilya")]
    assert pick_cards("Что приготовить на ужин") == []
