from pravoved.agent.graph import hit_key, parse_json
from pravoved.agent.verify import article_numbers, check_citations
from pravoved.retrieval.search import get_article


def sources():
    # реальные статьи из корпуса: ЗоЗПП ст. 18 и ТК ст. 236
    return [get_article("zozpp", "18"), get_article("tk", "236")]


def test_valid_markers():
    text, cited, invalid, used = check_citations("Можно вернуть деньги [1]. Компенсация [2].", sources())
    assert (cited, invalid, used) == (2, 0, [1, 2])
    assert text == "Можно вернуть деньги [1]. Компенсация [2]."


def test_marker_out_of_range_removed():
    text, cited, invalid, used = check_citations("Так можно [5]. А так тоже [1].", sources())
    assert (cited, invalid, used) == (2, 1, [1])
    assert "[5]" not in text and "[1]" in text


def test_marker_with_several_numbers():
    text, cited, invalid, used = check_citations("Право есть [1, 2, 7].", sources())
    assert (cited, invalid, used) == (3, 1, [1, 2])
    assert "[1, 2]" in text


def test_article_from_context_is_ok():
    text, cited, invalid, _ = check_citations("По статье 18 можно требовать замены.", sources())
    assert (cited, invalid) == (1, 0)
    assert "не подтверждено" not in text


def test_article_not_in_context_flagged():
    text, cited, invalid, _ = check_citations("Согласно ст. 99 это запрещено.", sources())
    assert (cited, invalid) == (1, 1)
    assert "ст. 99 [не подтверждено" in text


def test_article_from_tool_result_ok():
    _, cited, invalid, _ = check_citations("Неустойка по ст. 23 считается так.", sources(), "основание: ст. 23 п. 1 Закона")
    assert (cited, invalid) == (1, 0)


def test_dotted_article_number():
    assert article_numbers("ст. 23.1 и статья 18, а также статьёй 5") == {"23.1", "18", "5"}


def test_no_citations():
    _, cited, invalid, used = check_citations("Просто текст без ссылок.", sources())
    assert (cited, invalid, used) == (0, 0, [])


def test_parse_json_with_noise():
    assert parse_json('Вот ответ: {"enough": true, "query": ""} спасибо') == {"enough": True, "query": ""}
    assert parse_json("нет json") is None
    assert parse_json("{сломан}") is None


def test_hit_key():
    h = get_article("zozpp", "18")
    assert hit_key(h) == ("zozpp", "18", "")


def test_calc_words():
    from pravoved.agent.graph import CALC_WORDS
    assert CALC_WORDS.search("Какая сейчас ключевая ставка Банка России?")
    assert CALC_WORDS.search("Когда истекает срок?")
    assert not CALC_WORDS.search("Как получить налоговый вычет за лечение зубов?")
