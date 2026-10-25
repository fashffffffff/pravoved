import re
from decimal import Decimal

from pravoved.agent.verify import MARKER, SMALL, norm_num, word_numbers

# после этих слов точка не заканчивает предложение
ABBR = {"ст", "п", "пп", "ч", "руб", "тыс", "см", "им", "г", "гг", "т", "д", "е"}
BOUNDARY = re.compile(r"\n+|(?<=[.!?;])[ \t]+")
LIST_MARK = re.compile(r"\s*(?:\d+[.)]|[-•*])")
LEAD_MARKER = re.compile(r"\[\d+(?:\s*[,;]\s*\d+)*\][ \t]*")

ADJECTIVES = ("календарн", "рабоч", "полн")
NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)?")
YEAR_WORDS = {"год", "года", "году", "годом", "годы", "годов", "годам", "лет"}


def split_claims(answer):
    """Предложения и пункты списка, в которых есть ссылка [n].
    -> [{"text", "start", "end", "nums"}], start/end - место в answer"""
    spans = []
    start = 0
    for m in BOUNDARY.finditer(answer):
        piece = answer[start:m.start()]
        if "\n" not in m.group(0):
            last = re.search(r"(\w+)\.$", piece)
            if (last and last.group(1).lower() in ABBR) or LIST_MARK.fullmatch(piece.split("\n")[-1]):
                continue
        spans.append([start, m.start()])
        start = m.end()
    spans.append([start, len(answer)])

    claims = []
    for s, e in spans:
        lead = LEAD_MARKER.match(answer, s, e)
        # ссылка после точки относится к предыдущему предложению
        if lead and claims and "\n" not in answer[claims[-1]["end"]:s]:
            claims[-1]["end"] = s + len(lead.group(0).rstrip())
            s = lead.end()
        if answer[s:e].strip():
            claims.append({"start": s, "end": e})
    out = []
    for c in claims:
        c["text"] = answer[c["start"]:c["end"]].strip()
        c["nums"] = [int(n) for g in MARKER.findall(c["text"]) for n in re.findall(r"\d+", g)]
        if c["nums"]:
            out.append(c)
    return out


def unit_of(token):
    if token.startswith("месяц"):
        return "month"
    if token in YEAR_WORDS:
        return "year"
    if token.startswith("дн") or token in ("день", "дня"):
        return "day"
    if token.startswith("недел"):
        return "week"
    if token.startswith("процент") or token == "%":
        return "percent"
    return None


def is_number_token(token):
    return bool(NUM_TOKEN.fullmatch(token)) or token in SMALL or token.startswith(("тысяч", "миллион"))


def token_value(tokens):
    if len(tokens) == 1 and NUM_TOKEN.fullmatch(tokens[0]):
        return norm_num(tokens[0])
    found = word_numbers(" ".join(tokens))
    return norm_num(next(iter(found))) if found else ""


COMPOUND = re.compile(r"([а-яё]*?)(дневн|месячн|недельн|летн)\w*$")
COMPOUND_UNITS = {"дневн": "day", "месячн": "month", "недельн": "week", "летн": "year"}
# «в течение месяца», «не менее года»: без числа это один месяц, один год
ONE = {"месяц": "month", "месяца": "month", "год": "year", "года": "year", "неделя": "week", "недели": "week",
       "день": "day", "дня": "day"}


def number_runs(tokens):
    runs, run = [], []
    for t in tokens:
        if is_number_token(t):
            run.append(t)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def quantities(text, lenient=False):
    """Сроки и проценты из текста. -> {(единица, значение): как написано}.
    Годы переводятся в месяцы, недели в дни: «один год» и «12 месяцев» - одно и то же.
    lenient - для текста источника: берём и числа в скобках, и «месяца» как один месяц."""
    tokens = re.findall(r"\d+(?:[.,]\d+)?|[а-яё]+|%", text.lower())
    found = {}

    def add(unit, value, phrase):
        if not value:
            return
        number = Decimal(value)
        if unit == "year":
            # «2026 года» - это дата, а не срок
            if number >= 100:
                return
            unit, number = "month", number * 12
        elif unit == "week":
            unit, number = "day", number * 7
        found[(unit, norm_num(str(number)))] = phrase

    last_unit = -1
    for i, tok in enumerate(tokens):
        unit = unit_of(tok)
        compound = COMPOUND.match(tok)
        if compound and not unit:
            unit = COMPOUND_UNITS[compound.group(2)]
        if not unit:
            continue
        j = i - 1
        while j >= 0 and tokens[j].startswith(ADJECTIVES):
            j -= 1
        k = j
        while k >= 0 and is_number_token(tokens[k]):
            k -= 1
        phrase = " ".join(tokens[max(k + 1, 0):i + 1])
        if compound and not unit_of(tok):
            # «десятидневный» и «10-дневный»
            if compound.group(1) in SMALL:
                add(unit, token_value([compound.group(1)]), tok)
            elif k < j:
                add(unit, token_value(tokens[k + 1:j + 1]), phrase)
            elif lenient:
                add(unit, "1", tok)
        elif unit == "percent" and j >= 0 and tokens[j].startswith("половин"):
            add(unit, "0.5", phrase)
        elif k < j:
            add(unit, token_value(tokens[k + 1:j + 1]), phrase)
        elif lenient and tok in ONE:
            add(unit, "1", tok)
        if lenient:
            for run in number_runs(tokens[max(last_unit + 1, i - 15):i]):
                add(unit, token_value(run), phrase)
        last_unit = i
    return found


def number_mismatch(claim, backing):
    """Сроки и проценты из утверждения, которых нет в тексте источников.
    -> [(как в утверждении, что есть в источнике для той же величины)]"""
    have = quantities(backing, lenient=True)
    bad = []
    for (unit, value), phrase in quantities(claim).items():
        if (unit, value) in have:
            continue
        same = [p for (u, _), p in have.items() if u == unit]
        bad.append((phrase, same))
    return bad


def mismatch_reason(problems):
    parts = []
    for phrase, same in problems:
        if same:
            parts.append("в источнике нет «%s», там написано: %s" % (phrase, ", ".join(same[:3])))
        else:
            parts.append("в источнике нет «%s»" % phrase)
    return "; ".join(parts)


def pieces_of(text):
    pieces = []
    for p in text.split("\n"):
        if len(p) > 500:
            pieces += re.split(r"(?<=[.;])\s+", p)
        else:
            pieces.append(p)
    return [p for p in pieces if p.strip()]


def pick_excerpt(source, claim, limit=700):
    """Абзацы источника, которые ближе всего к утверждению (по общим словам и срокам)."""
    if len(source) <= limit:
        return source
    words = {w[:5] for w in re.findall(r"\w{4,}", MARKER.sub("", claim).lower())}
    wanted = set(quantities(claim))
    pieces = pieces_of(source)

    def score(p):
        s = sum(w in p.lower() for w in words)
        return s + 3 * len(wanted & set(quantities(p)))

    order = sorted(range(len(pieces)), key=lambda i: -score(pieces[i]))
    keep, size = [], 0
    for i in order:
        if size + len(pieces[i]) <= limit or not keep:
            keep.append(i)
            size += len(pieces[i]) + 1
    return "\n".join(pieces[i][:limit] for i in sorted(keep))


def plain(claim):
    # текст утверждения для показа: без ссылок и номера пункта списка
    text = re.sub(r"\s*" + MARKER.pattern, "", claim)
    text = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def drop_markers(answer, bad):
    """Убирает [n] из неподтверждённых утверждений. bad - утверждения из split_claims."""
    for c in sorted(bad, key=lambda c: -c["start"]):
        fixed = re.sub(r"[ \t]*" + MARKER.pattern, "", answer[c["start"]:c["end"]])
        answer = answer[:c["start"]] + fixed + answer[c["end"]:]
    return answer
