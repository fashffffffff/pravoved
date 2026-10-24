import re

from pravoved.retrieval.search import get_article

MARKER = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
# номера бывают с несколькими точками: ст. 5.27.1 КоАП
ARTICLE = re.compile(r"(?:\bст\.|\bстать[яиеёю]|\bстатьёй)\s*(\d+(?:\.\d+)*)", re.IGNORECASE)

# пункты Правил продажи (ПП №657): "п. 25 Правил продажи" и "Правила продажи (ПП №657), п. 25"
RULES = r"(?:Правил\w*\s+продажи|ПП\s*№?\s*657)"
POINT_BEFORE = re.compile(r"(?:\bп\.|\bпункт\w*)\s*(\d+)\s*" + RULES, re.IGNORECASE)
POINT_AFTER = re.compile(RULES + r"(?:\s*\(ПП\s*№?\s*657\))?,?\s*(?:п\.|пункт\w*)\s*(\d+)", re.IGNORECASE)
# в этих документах единицы - пункты, а не статьи
POINT_LAWS = ("plenum17", "pp657", "pp924")


def article_numbers(text):
    return set(ARTICLE.findall(text))


def rules_points(text):
    return set(POINT_BEFORE.findall(text)) | set(POINT_AFTER.findall(text))


def check_citations(answer, sources, tool_text="", n_web=0):
    """sources - список Hit в том порядке, как они пронумерованы в промпте, дальше идут n_web веб-источников
    (их номера [len(sources)+1 ...] тоже считаются существующими).
    Возвращает (текст без неверных ссылок, cited, invalid, номера использованных источников)."""
    cited = 0
    invalid = 0
    used = []

    def fix_marker(m):
        nonlocal cited, invalid
        good = []
        for n in re.findall(r"\d+", m.group(1)):
            cited += 1
            if 1 <= int(n) <= len(sources) + n_web:
                good.append(n)
                if int(n) not in used:
                    used.append(int(n))
            else:
                invalid += 1
        return "[%s]" % ", ".join(good) if good else ""

    text = MARKER.sub(fix_marker, answer)

    # статьи по номеру: должны быть в найденных источниках (или в ответе инструмента) и существовать в базе
    allowed = {s.article for s in sources if s.law not in POINT_LAWS and get_article(s.law, s.article)}
    allowed |= article_numbers(tool_text)

    def fix_article(m):
        nonlocal cited, invalid
        cited += 1
        if m.group(1) in allowed:
            return m.group(0)
        invalid += 1
        return m.group(0) + " [не подтверждено источниками]"

    text = ARTICLE.sub(fix_article, text)

    # пункты Правил продажи: должны быть среди найденных и существовать в базе
    points = {s.article for s in sources if s.law == "pp657" and get_article("pp657", s.article)}

    def fix_point(m):
        nonlocal cited, invalid
        cited += 1
        if m.group(1) in points:
            return m.group(0)
        invalid += 1
        return m.group(0) + " [не подтверждено источниками]"

    text = POINT_BEFORE.sub(fix_point, text)
    text = POINT_AFTER.sub(fix_point, text)
    text = re.sub(r"[ \t]+([.,;])", r"\1", text)
    return text, cited, invalid, sorted(used)


def unverified_cited(answer, n_local, web):
    """Сколько раз в тексте есть ссылка [n] на неподтверждённый веб-источник.
    web - список веб-источников (dict с ключом trust), нумерация продолжает локальные n_local."""
    count = 0
    for m in MARKER.finditer(answer):
        for n in re.findall(r"\d+", m.group(1)):
            i = int(n) - n_local - 1
            if 0 <= i < len(web) and web[i]["trust"] == "unverified":
                count += 1
    return count
