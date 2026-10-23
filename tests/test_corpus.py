from pravoved.corpus.parse import (
    article_units, plenum_units, find_refs, build_refs, split_articles, make_unit,
)

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
