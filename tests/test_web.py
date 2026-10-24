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


def test_web_enabled_env(monkeypatch):
    from pravoved.agent.graph import web_enabled
    monkeypatch.delenv("WEB_ENABLED", raising=False)
    assert web_enabled()
    monkeypatch.setenv("WEB_ENABLED", "false")
    assert not web_enabled()


def test_document_pages_are_official():
    assert trust_of("https://www.consultant.ru/document/cons_doc_LAW_305/") == "official"
    assert trust_of("https://base.garant.ru/10106035/") == "official"
    assert trust_of("https://www.garant.ru/products/ipo/prime/doc/70191362/") == "official"


def test_editorial_pages_are_authority():
    assert trust_of("https://www.consultant.ru/legalnews/12345/") == "authority"
    assert trust_of("https://www.consultant.ru/law/podborki/shtraf/") == "authority"
    assert trust_of("https://www.consultant.ru/law/hotdocs/") == "authority"
    assert trust_of("https://www.garant.ru/news/1234567/") == "authority"
    assert trust_of("https://www.garant.ru/article/1500000/") == "authority"
    assert trust_of("https://www.consultant.ru/") == "authority"
