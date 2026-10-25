from pravoved.agent.chat import find_file, is_contract_request
from pravoved.agent.claim import ClaimSession, is_claim_request, merge, missing_fields


def test_claim_intent():
    assert is_claim_request("Составь претензию продавцу")
    assert is_claim_request("помоги написать претензию, телефон сломался")
    assert not is_claim_request("Что такое претензия?")
    assert not is_claim_request("Купил телефон, он сломался")


def test_contract_intent():
    assert is_contract_request("проверь договор аренды")
    assert not is_contract_request("как расторгнуть договор?")


def test_find_file(tmp_path):
    f = tmp_path / "dogovor.txt"
    f.write_text("текст")
    assert find_file("проверь договор %s пожалуйста" % f) == f
    assert find_file("проверь договор /нет/такого.pdf") is None


def test_merge_ignores_empty_and_bad_kind():
    fields = {"sender_name": "Иванов"}
    merge(fields, {"sender_name": None, "recipient": "ООО Ромашка", "kind": "other", "price": ""})
    assert fields == {"sender_name": "Иванов", "recipient": "ООО Ромашка"}
    merge(fields, {"kind": "salary_delay"})
    assert fields["kind"] == "salary_delay"


def test_missing_fields_depend_on_kind():
    full = {"sender_name": "а", "sender_address": "б", "recipient": "в", "recipient_address": "г",
            "facts": "д", "demand": "е", "price": 100}
    assert missing_fields({**full, "kind": "consumer_refund"}) == []
    assert missing_fields({**full, "kind": "salary_delay"}) == ["due_date"]
    assert "price" in missing_fields({"kind": "consumer_refund"})


class FakeLlm:
    def __init__(self, replies):
        self.replies = list(replies)

    async def ainvoke(self, msgs):
        class Msg:
            content = self.replies.pop(0)
        return Msg()


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_session_asks_only_missing():
    llm = FakeLlm(['{"kind": "consumer_refund", "sender_name": "Иванов Иван", "price": 30000}'])
    s = ClaimSession(llm, [])
    reply = run(s.step("Составь претензию, телефон за 30000 сломался, я Иванов Иван"))
    assert "ваш адрес" in reply["text"]
    assert "ваше ФИО" not in reply["text"]
    assert not s.done


def test_session_cancel():
    s = ClaimSession(FakeLlm([]), [])
    run(s.step("отмена"))
    assert s.done


def test_draft_passes_prepaid_flag(monkeypatch):
    sent = {}

    async def fake_call(tools, name, args):
        sent[name] = args
        if name == "draft_claim":
            return {"path": "x.docx", "preview": "текст"}
        if name == "calc_deadline":
            return {"deadline": "2026-11-04"}
        return {"penalty": "100.00"}

    monkeypatch.setattr("pravoved.agent.claim.call_tool", fake_call)
    s = ClaimSession(FakeLlm([]), [])
    s.fields = {"kind": "consumer_penalty", "prepaid_delivery": True, "price": 1000, "due_date": "2026-10-01",
                "sender_name": "а", "sender_address": "б", "recipient": "в", "recipient_address": "г",
                "facts": "д", "demand": "е"}
    run(s.draft())
    assert sent["draft_claim"]["prepaid_delivery"] is True
    assert sent["calc_consumer_penalty"]["kind"] == "prepaid_delivery"
