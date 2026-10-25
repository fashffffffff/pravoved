import re

from langchain_core.messages import HumanMessage, SystemMessage

HISTORY_TURNS = 3
ANSWER_CHARS = 600

REWRITE_SYSTEM = """Ты помогаешь юридическому ассистенту понимать продолжение диалога.
Тебе дана история диалога и новое сообщение человека. Перепиши новое сообщение в один самостоятельный
вопрос, понятный без истории: добавь из диалога все важные факты (что случилось, суммы, даты, кто с кем).
Если человек отвечает на уточняющие вопросы ассистента, включи его ответы в вопрос.
Если сообщение и так самостоятельное и не связано с историей, верни его без изменений.
Не отвечай на вопрос и ничего не добавляй от себя. Выведи только переписанный вопрос."""

REWRITE_USER = """История:
{history}

Новое сообщение: {text}"""

# Новый текст ответа. В prompts.ANSWER_SYSTEM переносится вместо старого блока «Формат ответа».
ANSWER_STYLE = """Формат ответа (по умолчанию 120-180 слов, без пересказа определений из закона):
1. Первая строка - прямой вывод в 1-2 предложениях простыми словами, например «Скорее всего, возвращать не нужно».
2. «Почему:» - 2-4 коротких пункта, в каждом ссылка [n].
3. «Что делать:» - 2-4 коротких шага.
Термины объясняй по-человечески, без канцелярита.
Если для точного ответа не хватает ключевых фактов, всё равно дай предварительный вывод в форме «если ..., то ...»,
а в конце добавь блок «Уточните, пожалуйста:» с 1-3 конкретными вопросами. Вопрос должен менять ответ
(например «Цепочку уже передали вам в руки?»), а не быть просьбой «дайте больше информации».
Если вопрос продолжает диалог, учитывай историю и не повторяй то, что уже сказано.
Не задавай уточняющих вопросов, если фактов хватает."""

HISTORY_ADD = """

История диалога (для контекста; факты из неё можно использовать, но право строй только на источниках):
{history}"""

CLARIFY = re.compile(r"уточните", re.IGNORECASE)
CITE = re.compile(r"\[\d+\]")
# вопросительные предложения в блоке после «Уточните»
QUESTION = re.compile(r"[^\n?]*\?")


def short(text, limit=ANSWER_CHARS):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def format_history(history):
    """history - список пар (вопрос человека, ответ ассистента); берём последние ходы."""
    lines = []
    for q, a in history[-HISTORY_TURNS:]:
        lines.append("Человек: " + short(q))
        lines.append("Ассистент: " + short(a))
    return "\n".join(lines)


async def rewrite_question(llm, history, text):
    """Превращает реплику-продолжение в самостоятельный вопрос. -> (вопрос, usage или None)"""
    if not history:
        return text, None
    user = REWRITE_USER.format(history=format_history(history), text=text)
    msg = await llm.ainvoke([SystemMessage(REWRITE_SYSTEM), HumanMessage(user)])
    new = clean_rewrite(msg.content, text)
    return new, msg


def clean_rewrite(raw, text):
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip().strip("\"«»")
    # пустой или слишком длинный ответ модели - значит, она ответила вместо переписывания
    if not raw or len(raw) > 700:
        return text
    return raw


def answer_stats(answer):
    """Простая проверка формата ответа без LLM."""
    clarify = CLARIFY.search(answer)
    tail = answer[clarify.end():] if clarify else ""
    return {
        "words": len(answer.split()),
        "cites": len(CITE.findall(answer)),
        "has_why": "Почему" in answer,
        "has_steps": "Что делать" in answer,
        "clarify": bool(clarify),
        "questions": len(QUESTION.findall(tail)),
    }
