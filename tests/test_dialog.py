import asyncio
from types import SimpleNamespace

from pravoved.agent import dialog

HISTORY = [("Девушка подарила цепочку, требует вернуть", "Скорее всего, возвращать не нужно [1].")]


class FakeLlm:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def ainvoke(self, msgs):
        self.calls.append(msgs)
        return SimpleNamespace(content=self.reply)


def test_no_history_no_llm_call():
    llm = FakeLlm("лишнее")
    q, msg = asyncio.run(dialog.rewrite_question(llm, [], "Как вернуть товар?"))
    assert q == "Как вернуть товар?"
    assert msg is None and llm.calls == []


def test_rewrite_uses_history():
    llm = FakeLlm("Девушка подарила мне цепочку, есть переписка в телеграме. Нужно ли её возвращать?")
    q, _ = asyncio.run(dialog.rewrite_question(llm, HISTORY, "У меня есть переписка"))
    assert "цепочку" in q
    prompt = llm.calls[0][1].content
    assert "Девушка подарила цепочку" in prompt and "У меня есть переписка" in prompt


def test_bad_rewrite_falls_back():
    assert dialog.clean_rewrite("", "да") == "да"
    assert dialog.clean_rewrite("x" * 800, "да") == "да"
    assert dialog.clean_rewrite("<think>hm</think>«Нужно ли возвращать?»", "да") == "Нужно ли возвращать?"


def test_history_is_trimmed():
    history = [("вопрос %d" % i, "ответ " * 300) for i in range(6)]
    text = dialog.format_history(history)
    assert "вопрос 5" in text and "вопрос 2" not in text
    assert len(text) < 3 * 700


def test_answer_stats():
    answer = ("Скорее всего, возвращать не нужно.\nПочему:\n- Это подарок [1].\nЧто делать:\n1. Не отдавать.\n"
              "Уточните, пожалуйста:\n- Цепочку уже передали вам?\n- Был ли уговор вернуть её?")
    st = dialog.answer_stats(answer)
    assert st["has_why"] and st["has_steps"] and st["clarify"]
    assert st["cites"] == 1 and st["questions"] == 2


def test_answer_stats_without_clarify():
    st = dialog.answer_stats("Можно вернуть.\nПочему:\n- Так сказано [1].")
    assert not st["clarify"] and st["questions"] == 0
