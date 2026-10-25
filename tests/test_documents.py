import pytest
from docx import Document

from pravoved.mcp_server.documents import draft_claim_docx, make_calendar_event

DATA = {
    "sender_name": "Иванов Иван Иванович",
    "sender_address": "г. Казань, ул. Пушкина, д. 1, кв. 2",
    "recipient": "ООО «Ромашка»",
    "recipient_address": "г. Казань, ул. Ленина, д. 5",
    "facts": "12.09.2026 я купил смартфон за 30 000 руб. Через неделю он перестал включаться.",
    "demand": "Вернуть 30 000 руб., уплаченные за товар.",
    "date": "2026-10-24",
    "attachments": ["Копия чека", "Копия претензии"],
}


def docx_text(path):
    return "\n".join(p.text for p in Document(path).paragraphs)


@pytest.mark.parametrize(
    "kind, articles",
    [
        ("consumer_refund", ["Ст. 18", "Ст. 22", "п. 6 ст. 13", "50%"]),
        ("consumer_penalty", ["Ст. 23", "не может превышать сумму, уплаченную"]),
        ("salary_delay", ["Ст. 236", "Ст. 142", "15 дней", "прокуратур"]),
    ],
)
def test_claim_kinds(tmp_path, kind, articles):
    res = draft_claim_docx(kind, DATA, out_dir=str(tmp_path))
    assert res["path"].endswith(f"claim_{kind}_2026-10-24.docx")
    text = docx_text(res["path"])
    assert "ПРЕТЕНЗИЯ" in text
    assert "в течение 10 дней с момента получения" in text
    assert "1. Копия чека" in text
    for a in articles:
        assert a in text
    assert text == res["preview"]
    assert res["legal_basis"]


@pytest.mark.parametrize("value", ["2026-10-24", "24.10.2026"])
def test_claim_date_russian_format(tmp_path, value):
    res = draft_claim_docx("consumer_refund", {**DATA, "date": value}, out_dir=str(tmp_path))
    assert "24.10.2026" in res["preview"]
    assert "2026-10-24" not in res["preview"]


def test_claim_bad_date(tmp_path):
    res = draft_claim_docx("consumer_refund", {**DATA, "date": "завтра"}, out_dir=str(tmp_path))
    assert "error" in res


def test_claim_missing_fields(tmp_path):
    data = {k: v for k, v in DATA.items() if k not in ("facts", "demand")}
    res = draft_claim_docx("consumer_refund", data, out_dir=str(tmp_path))
    assert res["error"] == "не хватает данных"
    assert res["missing"] == ["facts", "demand"]
    assert not list(tmp_path.iterdir())


def test_claim_unknown_kind(tmp_path):
    assert "error" in draft_claim_docx("other", DATA, out_dir=str(tmp_path))


def test_ics(tmp_path):
    res = make_calendar_event(
        "Срок ответа, продавец", "2026-11-11", "Строка1\nстрока2; ещё", out_dir=str(tmp_path)
    )
    assert res["date"] == "2026-11-11"
    raw = open(res["path"], "rb").read().decode("utf-8")
    assert "BEGIN:VCALENDAR" in raw
    assert "DTSTART;VALUE=DATE:20261111" in raw
    assert "DTEND;VALUE=DATE:20261112" in raw
    assert "TRIGGER:-P1D" in raw
    assert "\\," in raw and "\\;" in raw and "\\n" in raw
    assert raw.endswith("END:VCALENDAR\r\n")
    assert "\n" not in raw.replace("\r\n", "")


def test_ics_bad_date(tmp_path):
    assert "error" in make_calendar_event("x", "завтра", out_dir=str(tmp_path))


def test_penalty_prepaid_cites_article_23_1(tmp_path):
    res = draft_claim_docx("consumer_penalty", {**DATA, "prepaid_delivery": True}, out_dir=str(tmp_path))
    assert "Ст. 23.1" in res["preview"]
    assert "половины процента" in res["preview"]
    assert "одного процента" not in res["preview"]
    assert "ЗоЗПП ст. 23.1 п. 3" in res["legal_basis"]


def test_penalty_default_stays_article_23(tmp_path):
    res = draft_claim_docx("consumer_penalty", DATA, out_dir=str(tmp_path))
    assert "23.1" not in res["preview"]
