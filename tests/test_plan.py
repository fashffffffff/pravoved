from pravoved.agent.plan import clean_plan, missing_items, present, quote_ok
from pravoved.agent.situation import filter_hits
from types import SimpleNamespace

SOURCE = "Работодатель обязан по семейным обстоятельствам предоставить работнику отпуск без сохранения заработной платы."


def test_quote_must_be_in_source():
    assert quote_ok("работодатель обязан предоставить работнику отпуск без сохранения заработной платы", SOURCE)
    assert not quote_ok("работодатель вправе отказать в отпуске по своему усмотрению", SOURCE)


def test_clean_plan_drops_fake_quote():
    data = {"norms": [{"n": 1, "quote": "работодатель обязан предоставить работнику отпуск без сохранения заработной платы"},
                      {"n": 1, "quote": "можно отказать если нет денег в бюджете компании"}],
            "must_say": [{"text": "отпуск до 5 дней", "n": 1, "keywords": ["5 дней"]}],
            "conclusion": "обязан", "conclusion_quote": "работодатель обязан предоставить работнику отпуск"}
    plan = clean_plan(data, {1: SOURCE})
    assert len(plan["norms"]) == 1
    assert plan["headline_backed"]


def test_missing_items_checks_numbers_and_words():
    item = {"text": "срок 14 дней", "n": 1, "keywords": ["14 дней"]}
    assert present(item, "Вернуть можно в течение 14 дней.")
    assert not present(item, "Вернуть можно в течение 7 дней.")
    plan = {"must_say": [item, {"text": "письменно", "n": 0, "keywords": ["письменно"]}]}
    assert missing_items(plan, "В течение 14 дней, устно") == ["письменно"]


def hit(law, regime=""):
    return SimpleNamespace(law=law, regime=regime)


def test_private_sale_drops_consumer_law():
    hits = [hit("zozpp"), hit("gk"), hit("pp657")]
    good, dropped = filter_hits(hits, "grazhdane")
    assert [h.law for h in good] == ["gk"]
    assert len(dropped) == 2


def test_prokat_goes_first():
    hits = [hit("gk", "arenda_obshchaya"), hit("gk", "prokat")]
    good, _ = filter_hits(hits, "prokat")
    assert good[0].regime == "prokat"
