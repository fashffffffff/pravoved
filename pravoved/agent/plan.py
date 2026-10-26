import re

from pravoved.agent.verify import norm_num

SPLIT_SYSTEM = """Тебе дан бытовой юридический вопрос. Разбей его на 2-3 коротких подвопроса для поиска по текстам законов РФ.
Каждый подвопрос - про свою сторону вопроса, языком закона: право или основание (что разрешено или запрещено),
сроки и порядок, исключения и перечни (когда нельзя, кому не положено), ответственность и последствия.
Бери только те стороны, что нужны для этого вопроса. Подвопрос - 5-12 слов, без бытовых слов.
Ответь одним JSON-объектом и больше ничем: {"queries": ["...", "..."]}"""

PLAN_SYSTEM = """Ты готовишь план ответа на юридический вопрос по пронумерованным источникам [1]..[n] (фрагменты законов).
Сам ответ не пиши. Достань из источников только то, что относится к вопросу, и ничего не выдумывай.

Ответь одним JSON-объектом и больше ничем:
{"parties": "кто стороны: бизнес и потребитель / работодатель и работник / два частных лица / другое",
 "norms": [{"n": 3, "quote": "точная цитата из источника, до 25 слов", "who": "кто обязан или вправе", "modality": "обязан | вправе | запрещено | не вправе | иное"}],
 "must_say": [{"text": "короткий факт, который нужно сказать в ответе (срок, сумма, исключение, обязанность, условие)", "n": 3, "keywords": ["слова или числа, которые будут в тексте ответа"]}],
 "unknown": ["чего не хватает в вопросе, что меняет ответ"],
 "conclusion": "прямой вывод для человека одним предложением",
 "conclusion_quote": "цитата из источника, на которой держится вывод, или пустая строка, если такой цитаты нет"}

Правила:
- quote - дословно из источника. Модальность (обязан или вправе) бери из текста, не меняй: если в норме «обязан», это не «может».
- В must_say включи главное для этого вопроса: срок, размер, условие, исключение или перечень, который может подойти,
  кто и что обязан сделать. До 6 пунктов, самые важные. keywords - 1-3 слова или числа, коротко, в начальной форме
  (например «14 дней», «письменно», «обязан»).
- Если источник из раздела другого режима (прокат, найм жилья, Крайний Север), а ситуация человека другая, не используй его.
- Нормы о защите прав потребителей (ЗоЗПП) применяются, только если одна сторона - организация или ИП, а другая - гражданин,
  который покупает или заказывает для личных нужд. Сделка между двумя частными лицами - это ГК, без ЗоЗПП.
- conclusion_quote пустая, если вывод приходится додумывать, а не брать из нормы."""

PLAN_USER = """Источники:
{sources}

Ситуация: {situation}
Вопрос: {question}"""

PLAN_ADD = """

План ответа (проверено по источникам). Обязательно скажи в ответе все пункты из «Надо сказать», в том числе сроки, суммы,
исключения и кто обязан. Модальность не меняй: «обязан» нельзя писать как «может» или «вправе».
Вывод в первой строке должен совпадать с телом ответа.
Стороны: {parties}
Нормы:
{norms}
Надо сказать:
{must}"""

PLAN_UNKNOWN_ADD = """
Не хватает данных: {unknown}. Спроси об этом в блоке «Уточните, пожалуйста:»."""

HEDGE_ADD = """
ВАЖНО: ни одна норма из источников прямо не подтверждает готовый вывод. Первая строка - условный вывод
«если ..., то ...», без категоричного «да» или «нет», и обязательно добавь блок «Уточните, пожалуйста:» с вопросом,
от которого зависит ответ."""

HEAD_SYSTEM = """Тебе дан ответ юридического помощника. Первая строка - вывод, дальше - обоснование.
Проверь, не противоречит ли первая строка обоснованию или плану. Противоречие: вывод говорит «нет, нельзя», а в обосновании
написано, что можно (или наоборот); вывод категоричный, а обоснование даёт исключения, которые его меняют;
в выводе «обязан», а в обосновании «может».
Ответь одним JSON-объектом и больше ничем: {"contradiction": true или false, "reason": "одна фраза, если true"}"""

HEAD_USER = """Ответ:
{answer}

Вывод по плану: {conclusion}"""

PLAN_FEEDBACK = """Проверка плана нашла недочёты в ответе:
{items}

Перепиши весь ответ в том же формате: исправь эти недочёты, остальное оставь. Не длиннее 170 слов."""


def words(text):
    return re.findall(r"\w+", text.lower())


def stem(word):
    return word[:5] if len(word) > 5 else word


def quote_ok(quote, source):
    # цитата должна реально быть в источнике: смотрим долю её слов в тексте источника
    q = [stem(w) for w in words(quote) if len(w) > 2]
    if len(q) < 3:
        return False
    have = {stem(w) for w in words(source)}
    return sum(w in have for w in q) / len(q) >= 0.8


def clean_plan(data, texts):
    """Оставляет в плане только то, что есть в источниках. texts - {номер источника: текст}."""
    plan = {"parties": str(data.get("parties") or ""), "norms": [], "must_say": [],
            "unknown": [str(u) for u in (data.get("unknown") or []) if str(u).strip()][:3],
            "conclusion": str(data.get("conclusion") or "").strip()}
    for norm in data.get("norms") or []:
        try:
            n = int(norm["n"])
        except (KeyError, TypeError, ValueError):
            continue
        quote = str(norm.get("quote") or "")
        if n in texts and quote_ok(quote, texts[n]):
            plan["norms"].append({"n": n, "quote": quote, "who": str(norm.get("who") or ""),
                                  "modality": str(norm.get("modality") or "")})
    for item in data.get("must_say") or []:
        try:
            n = int(item["n"])
        except (KeyError, TypeError, ValueError):
            n = 0
        text = str(item.get("text") or "").strip()
        keys = [str(k) for k in (item.get("keywords") or []) if str(k).strip()]
        if text and (n in texts or not n):
            plan["must_say"].append({"text": text, "n": n, "keywords": keys})
    quote = str(data.get("conclusion_quote") or "")
    plan["headline_backed"] = any(quote_ok(quote, t) for t in texts.values()) if quote else False
    return plan


def format_plan(plan):
    norms = "\n".join("- [%d] «%s» (%s: %s)" % (n["n"], n["quote"], n["modality"], n["who"]) for n in plan["norms"])
    must = "\n".join("- %s%s" % (m["text"], " [%d]" % m["n"] if m["n"] else "") for m in plan["must_say"])
    text = PLAN_ADD.format(parties=plan["parties"] or "не определены", norms=norms or "нет", must=must or "нет")
    if plan["unknown"]:
        text += PLAN_UNKNOWN_ADD.format(unknown="; ".join(plan["unknown"]))
    if not plan["headline_backed"]:
        text += HEDGE_ADD
    return text


def present(item, answer):
    """Есть ли пункт плана в тексте ответа: все числа и не меньше половины ключевых слов."""
    low = answer.lower()
    answer_nums = {norm_num(x) for x in re.findall(r"\d+(?:[.,]\d+)?", low)}
    answer_stems = {stem(w) for w in words(low)}
    keys = item["keywords"] or [item["text"]]
    nums = {norm_num(x) for k in keys for x in re.findall(r"\d+(?:[.,]\d+)?", k)}
    if nums and not nums <= answer_nums:
        return False
    stems = [stem(w) for k in keys for w in words(k) if not w.isdigit() and len(w) > 2]
    if not stems:
        return True
    return sum(s in answer_stems for s in stems) / len(stems) >= 0.5


def missing_items(plan, answer):
    return [m["text"] for m in plan["must_say"] if not present(m, answer)]
