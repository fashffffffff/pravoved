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


def normalize_markers(text):
    """«[9, ч. 1 п. 3]» и «[11, ст. 18; 4, ст. 475]» -> «[9]» и «[11, 4]»: оставляем только номера источников"""
    def fix(m):
        inner = m.group(1)
        if not re.search(r"[а-яё]", inner, re.IGNORECASE):
            return m.group(0)
        # номера после «ст.», «ч.», «п.» - не номера источников, берём только первое число до «;» или запятой с текстом
        nums = re.findall(r"(?:^|;\s*)(\d+)", inner)
        return "[%s]" % ", ".join(nums) if nums else m.group(0)
    return re.sub(r"\[(\d[^\]]*)\]", fix, text)


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

    text = MARKER.sub(fix_marker, normalize_markers(answer))

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


def strip_unverified(answer, n_local, web):
    """Убирает из текста маркеры [n], которые указывают на неподтверждённые веб-источники."""
    def fix(m):
        keep = []
        for n in re.findall(r"\d+", m.group(1)):
            i = int(n) - n_local - 1
            if not (0 <= i < len(web) and web[i]["trust"] == "unverified"):
                keep.append(n)
        return "[%s]" % ", ".join(keep) if keep else ""

    text = MARKER.sub(fix, answer)
    return re.sub(r"[ \t]+([.,;])", r"\1", text)


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


# в кодексах суммы пишут словами: "от трех тысяч до пяти тысяч рублей"
SMALL = {"одного": 1, "одной": 1, "один": 1, "одна": 1, "двух": 2, "два": 2, "две": 2, "трех": 3, "трёх": 3, "три": 3,
         "четырех": 4, "четырёх": 4, "четыре": 4, "пяти": 5, "пять": 5, "шести": 6, "шесть": 6, "семи": 7, "семь": 7,
         "восьми": 8, "восемь": 8, "девяти": 9, "девять": 9, "десяти": 10, "десять": 10, "одиннадцати": 11,
         "двенадцати": 12, "тринадцати": 13, "четырнадцати": 14, "пятнадцати": 15, "шестнадцати": 16,
         "семнадцати": 17, "восемнадцати": 18, "девятнадцати": 19, "двадцати": 20, "двадцать": 20, "тридцати": 30,
         "тридцать": 30, "сорока": 40, "сорок": 40, "пятидесяти": 50, "пятьдесят": 50, "шестидесяти": 60,
         "шестьдесят": 60, "семидесяти": 70, "семьдесят": 70, "восьмидесяти": 80, "восемьдесят": 80,
         "девяноста": 90, "девяносто": 90, "ста": 100, "сто": 100, "двухсот": 200, "двести": 200, "трехсот": 300,
         "трёхсот": 300, "триста": 300, "четырехсот": 400, "четырёхсот": 400, "четыреста": 400, "пятисот": 500,
         "пятьсот": 500, "шестисот": 600, "шестьсот": 600, "семисот": 700, "семьсот": 700, "восьмисот": 800,
         "восемьсот": 800, "девятисот": 900, "девятьсот": 900}


def word_numbers(text):
    """Числа, записанные словами: "двадцати тысяч" -> {"20000"}"""
    found = set()
    total = current = 0
    for word in re.findall(r"[а-яё]+|\W", text.lower()) + ["."]:
        if word in SMALL:
            current += SMALL[word]
        elif word.startswith("тысяч"):
            total += max(current, 1) * 1000
            current = 0
        elif word.startswith("миллион"):
            total += max(current, 1) * 1000000
            current = 0
        elif not word.isspace() or not (total or current):
            # пробел внутри числа не обрывает его, всё остальное обрывает
            if total or current:
                found.add(str(total + current))
            total = current = 0
    return found


def unbacked_numbers(answer, backing):
    """Суммы, проценты и даты из ответа, которых нет в backing (вопрос, ответы инструментов, цитируемые источники)."""
    have = {norm_num(n) for n in re.findall(NUM, backing)}
    have |= {norm_num(n) for n in re.findall(r"\d+(?:[.,]\d+)?", backing)}
    have |= word_numbers(backing)
    bad = [text for value, text in find_amounts(answer).items() if value not in have]
    have_days = set(find_dates(backing))
    bad += [text for key, text in find_dates(answer).items() if key not in have_days]
    return list(dict.fromkeys(bad))


def only_unverified(sources):
    return bool(sources) and all(s["trust"] == "unverified" for s in sources)
