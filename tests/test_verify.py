from pravoved.agent.graph import hit_key, parse_json
from pravoved.agent.verify import article_numbers, check_citations, rules_points, unverified_cited
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


WEB = [{"trust": "official"}, {"trust": "unverified"}, {"trust": "draft"}]


def test_web_marker_is_valid():
    # два локальных источника, веб идёт с номера 3
    text, cited, invalid, used = check_citations("Штраф есть [3]. Ещё [5].", sources(), n_web=3)
    assert (cited, invalid, used) == (2, 0, [3, 5])


def test_web_marker_without_web_is_invalid():
    _, _, invalid, _ = check_citations("Штраф есть [3].", sources())
    assert invalid == 1


def test_unverified_cited_counts_only_unverified():
    assert unverified_cited("Так [3]. И так [4]. И ещё [5].", 2, WEB) == 1
    assert unverified_cited("Оба [3, 4].", 2, WEB) == 1
    assert unverified_cited("Только [1] и [3].", 2, WEB) == 0
    assert unverified_cited("Нет ссылок.", 2, WEB) == 0
    assert unverified_cited("[4] [4]", 2, WEB) == 2


def test_web_words():
    from pravoved.agent.graph import WEB_WORDS
    assert WEB_WORDS.search("Какой штраф для работодателя за задержку зарплаты?")
    assert WEB_WORDS.search("Что изменилось в ТК с 1 сентября 2026?")
    assert not WEB_WORDS.search("Телефон сломался через неделю, что делать?")
    assert WEB_WORDS.search("Принят ли закон о четырёхдневной рабочей неделе?")
    assert WEB_WORDS.search("Можно ли сейчас вернуть деньги за подписку?")


def test_article_with_two_dots():
    assert article_numbers("штраф по ст. 5.27.1 КоАП РФ и статье 5.27") == {"5.27.1", "5.27"}


def test_koap_article_from_sources():
    src = [get_article("koap", "5.27.1")]
    _, cited, invalid, _ = check_citations("Штраф назначают по ст. 5.27.1 КоАП РФ [1].", src)
    assert (cited, invalid) == (2, 0)
    text, _, invalid, _ = check_citations("Ещё есть ст. 5.27.2.", src)
    assert invalid == 1 and "[не подтверждено" in text


def test_rules_points():
    assert rules_points("по п. 25 Правил продажи и пункту 11 Правил продажи") == {"25", "11"}
    assert rules_points("Правила продажи (ПП №657), п. 25") == {"25"}
    assert rules_points("п. 25 договора") == set()


def test_rules_point_checked():
    src = [get_article("pp657", "25")]
    text, _, invalid, _ = check_citations("Это следует из п. 25 Правил продажи [1].", src)
    assert invalid == 0 and "не подтверждено" not in text
    text, _, invalid, _ = check_citations("Это следует из п. 26 Правил продажи [1].", src)
    assert invalid == 1 and "п. 26 Правил продажи [не подтверждено" in text


def test_point_of_rules_does_not_confirm_article():
    # п. 25 Правил продажи в источниках не делает верной ст. 25 ЗоЗПП
    src = [get_article("pp657", "25")]
    _, _, invalid, _ = check_citations("Обмен по ст. 25.", src)
    assert invalid == 1


def test_lists_exist_in_corpus():
    for law, article in [("pp657", "obmen"), ("pp657", "remont"), ("pp924", "perechen")]:
        assert get_article(law, article) is not None
