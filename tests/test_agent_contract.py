import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from contract_eval import parse_labels, score  # noqa: E402
from pravoved.agent.contract import contract_kind, make_batches, norm_color, split_clauses  # noqa: E402

CASES = ROOT / "eval" / "contract_cases"

TEXT = """ДОГОВОР КУПЛИ-ПРОДАЖИ

г. Самара, 14 октября 2026 г.
Стороны заключили договор.

1. ПРЕДМЕТ ДОГОВОРА
1.1. Продавец передаёт Покупателю холодильник за 64 900 рублей.
1.2. Оплата производится при заказе,
до передачи товара.
2. ГАРАНТИЯ
2. Гарантийный срок составляет шесть месяцев со дня передачи товара.
3. РЕКВИЗИТЫ И ПОДПИСИ СТОРОН
3.1. Продавец: ООО «Домовой», ИНН 6318001122, г. Самара, ул. Мичурина, д. 5.
Подпись ____________
"""


def test_split_numbered_clauses():
    clauses = split_clauses(TEXT)
    assert [c["id"] for c in clauses] == ["1.1", "1.2", "2"]
    # продолжение строки присоединяется к пункту
    assert clauses[1]["text"].endswith("до передачи товара.")
    assert clauses[0]["section"] == "ПРЕДМЕТ ДОГОВОРА"


def test_split_skips_requisites_and_preamble():
    text = " ".join(c["text"] for c in split_clauses(TEXT))
    assert "ИНН" not in text
    assert "Стороны заключили" not in text


def test_split_paragraphs_without_numbers():
    clauses = split_clauses("Продавец не несёт ответственности за недостатки товара.\n\nСпоры рассматриваются по месту нахождения продавца.")
    assert [c["id"] for c in clauses] == ["п1", "п2"]


def test_split_ignores_dates_at_line_start():
    text = "1. ПРЕДМЕТ\n1.1. Срок действия договора:\n15 января 2027 года и до полного исполнения обязательств.\n"
    clauses = split_clauses(text)
    assert len(clauses) == 1
    assert "15 января" in clauses[0]["text"]


def test_batches_limit_size():
    clauses = [{"id": str(i), "text": "x" * 100, "section": ""} for i in range(12)]
    batches = make_batches(clauses)
    assert [len(b) for b in batches] == [5, 5, 2]


def test_contract_kind():
    assert contract_kind("Работодатель и Работник заключили трудовой договор. Работник обязан") == "labour"
    assert contract_kind("Наймодатель сдаёт Нанимателю квартиру, найм жилого помещения") == "rent"
    assert contract_kind("Продавец передаёт Покупателю товар") == "consumer"


def test_norm_color():
    assert norm_color("RED") == "red"
    assert norm_color("🟢") == "green"
    assert norm_color("что-то") == "yellow"


def test_parse_labels():
    labels = parse_labels("# комментарий\n2.2 red gk:682\n3.4 red -\n4.1 green\n4.2 red tk:80|tk:232\n")
    assert labels["2.2"] == {"color": "red", "articles": {"gk:682"}}
    assert labels["3.4"]["articles"] == set()
    assert labels["4.2"]["articles"] == {"tk:80", "tk:232"}
    with pytest.raises(ValueError):
        parse_labels("1.1 blue")


def test_score():
    labels = parse_labels("1.1 green\n1.2 red gk:682\n1.3 red -\n1.4 yellow")
    clauses = [{"id": "1.1", "color": "green", "cites": []},
               {"id": "1.2", "color": "red", "cites": [{"law": "gk", "article": "682"}]},
               {"id": "1.3", "color": "yellow", "cites": []},
               {"id": "1.4", "color": "red", "cites": []}]
    s = score(labels, clauses)
    assert (s["red_tp"], s["red_pred"], s["red_true"]) == (1, 2, 2)
    assert s["agree"] == 2
    assert (s["article_ok"], s["article_total"]) == (1, 1)


@pytest.mark.parametrize("name", ["rent", "labour", "consumer"])
def test_case_files_match_split(name):
    # разметка относится к пунктам, которые разбиение действительно находит
    clauses = split_clauses((CASES / (name + ".txt")).read_text(encoding="utf-8"))
    labels = parse_labels((CASES / (name + ".labels")).read_text(encoding="utf-8"))
    assert {c["id"] for c in clauses} == set(labels)
    assert any(v["color"] == "red" for v in labels.values())
