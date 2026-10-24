import re
from decimal import Decimal, InvalidOperation

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


NUM = r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
MONEY = re.compile(r"(%s)(?:\s*(?:до|-|–)\s*(%s))?(\s*тыс\.?)?\s*(?:₽|руб\w*|р\.)" % (NUM, NUM), re.IGNORECASE)
PERCENT = re.compile(r"(%s)\s*(?:%%|процент)" % NUM)
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]
DATE_WORDS = re.compile(r"\b(\d{1,2})\s+(%s)(?:\s+(\d{4}))?" % "|".join(MONTHS), re.IGNORECASE)
DATE_DOTS = re.compile(r"\b(\d{1,2})\.(\d{2})\.(\d{4})\b")
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def norm_num(s):
    try:
        d = Decimal(re.sub(r"\s", "", s).replace(",", "."))
    except InvalidOperation:
        return ""
    return format(d.normalize(), "f")


def day_key(day, month):
    return "%02d-%02d" % (int(month), int(day))


def find_dates(text):
    # дата сравнивается без года: в ответе "18 мая" и "18.05.2026" - одна дата
    found = {}
    for m in DATE_WORDS.finditer(text):
        found[day_key(m.group(1), MONTHS.index(m.group(2).lower()) + 1)] = m.group(0)
    for d, m, y in DATE_DOTS.findall(text):
        found[day_key(d, m)] = "%s.%s.%s" % (d, m, y)
    for y, m, d in DATE_ISO.findall(text):
        found[day_key(d, m)] = "%s.%s.%s" % (d, m, y)
    return found


def find_amounts(text):
    """Суммы в рублях и проценты из текста: {нормализованное число: как написано}"""
    found = {}
    for m in MONEY.finditer(text):
        for n in (m.group(1), m.group(2)):
            if not n:
                continue
            value = norm_num(n)
            if m.group(3) and value:
                value = norm_num(str(Decimal(value) * 1000))
            found[value] = m.group(0).strip()
    for m in PERCENT.finditer(text):
        found[norm_num(m.group(1))] = m.group(0).strip()
    found.pop("", None)
    return found


def unbacked_numbers(answer, backing):
    """Суммы, проценты и даты из ответа, которых нет в backing (вопрос, ответы инструментов, цитируемые источники)."""
    have = {norm_num(n) for n in re.findall(NUM, backing)}
    have |= {norm_num(n) for n in re.findall(r"\d+(?:[.,]\d+)?", backing)}
    bad = [text for value, text in find_amounts(answer).items() if value not in have]
    have_days = set(find_dates(backing))
    bad += [text for key, text in find_dates(answer).items() if key not in have_days]
    return bad


def only_unverified(sources):
    return bool(sources) and all(s["trust"] == "unverified" for s in sources)
