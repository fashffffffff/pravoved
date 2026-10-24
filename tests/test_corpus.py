from pravoved.corpus.parse import (
    article_units, plenum_units, find_refs, build_refs, split_articles, make_unit,
    point_units, list_units, section_text, list_body,
)
from pravoved.retrieval.store import citation

TEXT = """Статья 18. Права потребителя при обнаружении недостатков
1. Потребитель вправе потребовать замены товара.
Статья 19.1. Особый порядок
Текст статьи со ссылкой на статью 18 настоящего Закона.
Статья 20. Утратила силу
Утратила силу.
"""


def test_split_articles_keeps_dotted_numbers():
    arts = split_articles(TEXT)
    assert [a[0] for a in arts] == ["18", "19.1", "20"]
    assert arts[0][1].startswith("Права потребителя")


def test_article_units_skips_repealed():
    units = article_units("zozpp", TEXT)
    assert [u["id"] for u in units] == ["zozpp:18", "zozpp:19.1"]


def test_long_article_split_by_parts():
    lines = ["Статья 5. Длинная"]
    for i in range(1, 6):
        lines.append("%d. " % i + "слово " * 150)
    units = article_units("tk", "\n".join(lines))
    assert len(units) > 1
    assert all(u["article"] == "5" for u in units)
    assert units[0]["part"].startswith("1")


def test_plenum_points():
    text = "преамбула\n## Раздел\n1. Первый пункт\nпродолжение\n2. Второй пункт\n"
    units = plenum_units(text)
    assert [u["article"] for u in units] == ["1", "2"]
    assert "продолжение" in units[0]["text"]
    assert units[0]["title"] == "Раздел"


def test_refs_own_law():
    assert find_refs("zozpp", "см. статьей 18 настоящего Закона") == [("zozpp", "18")]


def test_refs_other_law_and_list():
    refs = find_refs("tk", "статьи 236 и 237 ГК РФ")
    assert refs == [("gk", "236"), ("gk", "237")]


def test_refs_foreign_act_ignored():
    assert find_refs("tk", "статьей 126 Конституции Российской Федерации") == []
    assert find_refs("zozpp", "статьи 333 ГПК РФ") == []


def test_plenum_law_reference():
    assert find_refs("plenum17", "статьей 28 Закона о защите прав потребителей") == [("zozpp", "28")]


def test_build_refs_only_known_articles():
    units = [
        make_unit("zozpp", "18", "", "t", "см. статью 19 настоящего Закона и статью 99 настоящего Закона"),
        make_unit("zozpp", "19", "", "t", "текст"),
    ]
    assert build_refs(units) == [("zozpp:18", "zozpp:19")]


def test_article_with_two_dots():
    arts = split_articles("Статья 5.27.1. Охрана труда\n1. Текст\nСтатья 14.4. Продажа\nТекст")
    assert [a[0] for a in arts] == ["5.27.1", "14.4"]


def test_refs_koap():
    assert find_refs("tk", "статьей 5.27 КоАП РФ") == [("koap", "5.27")]
    assert find_refs("koap", "статьей 5.27.1 настоящего Кодекса") == [("koap", "5.27.1")]


def test_point_units_title_is_section():
    text = "## Правила\nУтверждены\n## Общие\n1. Первый\nещё строка\n2. Второй\n"
    units = point_units("pp657", text)
    assert [u["id"] for u in units] == ["pp657:1", "pp657:2"]
    assert units[0]["title"] == "Общие"


def test_list_units_single_piece():
    text = "## Перечень\nУтвержден\nПЕРЕЧЕНЬ\n1. Телевизоры\n2. Холодильники\n"
    body = list_body(section_text(text, "Перечень"))
    units = list_units("pp924", "perechen", "Перечень", body)
    assert [u["id"] for u in units] == ["pp924:perechen"]
    assert units[0]["text"].startswith("1. Телевизоры")


def test_citations_new_laws():
    assert citation("koap", "5.27") == "КоАП РФ, ст. 5.27"
    assert citation("pp657", "25") == "Правила продажи (ПП №657), п. 25"
    assert citation("pp657", "obmen") == "Правила продажи (ПП №657), перечень товаров, не подлежащих обмену"
    assert citation("pp924", "perechen") == "Перечень технически сложных товаров (ПП №924)"
