from pravoved.agent.graph import relevant_part, source_list
from pravoved.mcp_server.web import trust_of


def test_trust_levels():
    assert trust_of("https://www.consultant.ru/document/cons_doc_LAW_1/") == "official"
    assert trust_of("http://publication.pravo.gov.ru/Document/View/1") == "official"
    assert trust_of("https://77.rospotrebnadzor.ru/news") == "authority"
    assert trust_of("https://онлайнинспекция.рф/") == "authority"
    assert trust_of("https://sozd.duma.gov.ru/bill/1") == "draft"
    assert trust_of("https://example.com/consultant.ru") == "unverified"
    assert trust_of("https://fakeconsultant.ru") == "unverified"
    assert trust_of("https://consultant.ru.evil.com") == "unverified"


def test_relevant_part_picks_paragraphs_by_question():
    text = "\n".join(["про погоду и ничего больше " * 20] * 5 + ["штраф за задержку зарплаты по статье 5.27"])
    part = relevant_part(text, "какой штраф за задержку зарплаты", 200)
    assert "штраф за задержку" in part
    assert len(part) <= 200


def test_source_list_marks_web():
    web = [{"url": "https://consultant.ru/x", "title": "КоАП", "trust": "official", "date": "2026-01-01", "text": "текст"}]
    out = source_list([], web)
    assert out.startswith("[1] ВЕБ, доверие: official, https://consultant.ru/x, дата: 2026-01-01")
    assert "<<<\nтекст\n>>>" in out
