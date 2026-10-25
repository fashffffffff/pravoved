import asyncio
from types import SimpleNamespace

from pravoved.agent.faith import (drop_markers, mismatch_reason, number_mismatch, pick_excerpt, plain, quantities,
                                  split_claims)
from pravoved.agent.graph import build_graph, faith_enabled

TK_392 = ("Работник имеет право обратиться в суд за разрешением индивидуального трудового спора "
          "в течение трех месяцев со дня, когда он узнал или должен был узнать о нарушении своего права.")


def test_split_claims_sentences_and_bullets():
    answer = ("Срок три месяца [1]. Это общее правило, без ссылки. Иногда больше [2, 3].\n\n"
              "Что делать:\n1. Подайте заявление в течение 10 дней [2].\n2. Соберите документы.")
    claims = split_claims(answer)
    assert [c["nums"] for c in claims] == [[1], [2, 3], [2]]
    assert claims[0]["text"] == "Срок три месяца [1]."
    assert plain(claims[2]["text"]) == "Подайте заявление в течение 10 дней."
    for c in claims:
        assert answer[c["start"]:c["end"]].strip() == c["text"]


def test_split_claims_keeps_abbreviations_and_late_marker():
    claims = split_claims("По ст. 392 ТК РФ срок три месяца. [1] Дальше без ссылок.")
    assert len(claims) == 1
    assert claims[0]["text"] == "По ст. 392 ТК РФ срок три месяца. [1]"


def test_pick_excerpt_takes_relevant_paragraph():
    source = "\n".join(["Первый абзац про аренду жилья и плату " * 8,
                        "Работник вправе обратиться в суд в течение трех месяцев " * 3,
                        "Третий абзац про отпуск и увольнение " * 8])
    got = pick_excerpt(source, "Обратиться в суд можно в течение трех месяцев [1]", limit=200)
    assert "в суд" in got
    assert "аренду" not in got
    assert pick_excerpt("коротко", "что угодно") == "коротко"


def test_excerpt_prefers_paragraph_with_same_number():
    source = "Срок обращения в суд.\n" + "в течение трех месяцев работник обращается в суд " * 4 + "\n" + \
             "по ущербу работодатель обращается в суд в течение одного года " * 4
    got = pick_excerpt(source, "Обратиться в суд можно в течение одного года", limit=250)
    assert "одного года" in got


def test_quantities_words_and_digits():
    q = quantities("в течение трех месяцев, 10 календарных дней, 0,5% в день, одной недели и двух лет")
    assert ("month", "3") in q
    assert ("day", "10") in q
    assert ("percent", "0.5") in q
    assert ("day", "7") in q
    assert ("month", "24") in q


def test_year_equals_twelve_months_and_dates_ignored():
    assert quantities("один год") == {("month", "12"): "один год"}
    assert quantities("в 2026 году") == {}
    assert ("percent", "0.5") in quantities("половины процента цены")


def test_392_one_year_vs_three_months_caught():
    problems = number_mismatch("Срок обращения в суд - один год [1].", TK_392)
    assert problems
    reason = mismatch_reason(problems)
    assert "один год" in reason
    assert "трех месяцев" in reason


def test_matching_terms_pass():
    assert number_mismatch("Обратиться можно в течение 3 месяцев [1].", TK_392) == []
    assert number_mismatch("Срок - три месяца [1].", TK_392) == []
    assert number_mismatch("Срок - 90 дней", "срок три месяца") != []
    assert number_mismatch("Ответ в течение десяти дней", "в течение 10 дней со дня предъявления") == []
    assert number_mismatch("Неустойка 1% в день", "в размере одного процента цены товара") == []
    assert number_mismatch("Неустойка 3% в день", "в размере одного процента цены товара") != []
    assert number_mismatch("Нет сроков вообще [1].", TK_392) == []


def test_drop_markers_only_in_bad_claims():
    answer = "Срок один год [1]. Это верно [2].\nШаг: подайте иск [1, 2]."
    claims = split_claims(answer)
    text = drop_markers(answer, [claims[0], claims[2]])
    assert text == "Срок один год. Это верно [2].\nШаг: подайте иск."


# узел faithfulness целиком, с поддельной моделью

class Hit(SimpleNamespace):
    pass


class FakeLlm:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def bind_tools(self, tools, **kw):
        return self

    async def ainvoke(self, msgs):
        self.calls += 1
        text = self.replies.pop(0)
        return SimpleNamespace(content=text, tool_calls=[], usage_metadata={})


def run_faith(replies, answer, monkeypatch):
    # граф собираем, а затем вызываем только узел проверки
    monkeypatch.setenv("FAITH_CHECK", "true")
    llm = FakeLlm(replies)
    graph = build_graph(llm, [])
    node = graph.nodes["faithfulness"].bound
    state = {"answer": answer, "question": "срок?", "tool_calls": [], "web_sources": [],
             "hits": [Hit(text=TK_392)]}
    return llm, asyncio.run(node.ainvoke(state))


def test_node_numbers_caught_without_llm(monkeypatch):
    llm, res = run_faith([], "Срок один год [1].", monkeypatch)
    assert llm.calls == 0
    assert res["claims_checked"] == 1 and res["claims_unsupported"] == 1
    assert res["faith_again"] is True
    assert "три" in res["faith_feedback"] or "трех" in res["faith_feedback"]


def test_node_llm_verdict_used(monkeypatch):
    reply = '{"verdicts": [{"id": 1, "verdict": "not_supported", "reason": "про другое"}]}'
    llm, res = run_faith([reply], "Работник может обратиться в суд [1].", monkeypatch)
    assert llm.calls == 1
    assert res["claims_unsupported"] == 1
    assert res["faith_issues"][0]["by"] == "llm"


def test_node_supported_and_bad_json(monkeypatch):
    llm, res = run_faith(["не json"], "Работник может обратиться в суд [1].", monkeypatch)
    assert res["claims_checked"] == 1 and res["claims_unsupported"] == 0
    assert res["faith_again"] is False


def test_node_second_round_strips_and_warns(monkeypatch):
    monkeypatch.setenv("FAITH_CHECK", "true")
    graph = build_graph(FakeLlm([]), [])
    node = graph.nodes["faithfulness"].bound
    state = {"answer": "Срок один год [1].", "question": "срок?", "tool_calls": [], "web_sources": [],
             "hits": [Hit(text=TK_392)], "faith_round": 1, "claims_unsupported": 1}
    res = asyncio.run(node.ainvoke(state))
    assert "[1]" not in res["answer"].split("Не подтверждено")[0]
    assert "Не подтверждено источником: Срок один год" in res["answer"]
    assert res["claims_fixed"] == 0 and res["claims_unresolved"] == 1


def test_node_second_round_counts_fixed(monkeypatch):
    monkeypatch.setenv("FAITH_CHECK", "true")
    graph = build_graph(FakeLlm(['{"verdicts": []}']), [])
    node = graph.nodes["faithfulness"].bound
    state = {"answer": "Срок три месяца [1].", "question": "срок?", "tool_calls": [], "web_sources": [],
             "hits": [Hit(text=TK_392)], "faith_round": 1, "claims_unsupported": 1}
    res = asyncio.run(node.ainvoke(state))
    assert res["claims_fixed"] == 1
    assert "answer" not in res


def test_faith_flag(monkeypatch):
    monkeypatch.delenv("FAITH_CHECK", raising=False)
    assert faith_enabled()
    monkeypatch.setenv("FAITH_CHECK", "false")
    assert not faith_enabled()
