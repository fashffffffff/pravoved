"""Режет сырые тексты из data/raw на единицы (статья / часть статьи / пункт пленума)
и достаёт ссылки между статьями."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CHUNKS = ROOT / "data" / "chunks.jsonl"
REFS = ROOT / "data" / "refs.jsonl"

MAX_LEN = 1500   # длиннее - режем по частям
MIN_PART = 500   # короткие части склеиваем

ARTICLE_RE = re.compile(r"^Статья (\d+(?:\.\d+)*)\.\s*(.*)$")
PART_RE = re.compile(r"^(\d+)\.\s")
POINT_RE = re.compile(r"^(\d+)\.\s")

PLENUM_TITLE = "Постановление Пленума ВС РФ от 28.06.2012 N 17"

LAW_FILES = ["zozpp", "tk", "gk", "koap", "plenum17", "pp657", "pp924"]


def split_articles(text):
    """-> список (номер, заголовок, [строки])"""
    articles = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = ARTICLE_RE.match(line)
        if m:
            articles.append((m.group(1), m.group(2).strip(), []))
        elif articles:
            articles[-1][2].append(line)
    return articles


def split_long(lines):
    """Режем длинную статью по номерам частей. -> список (часть, текст)"""
    parts = []  # [номер, [строки]]
    for line in lines:
        m = PART_RE.match(line)
        if m or not parts:
            parts.append([m.group(1) if m else "", [line]])
        else:
            parts[-1][1].append(line)

    # склеиваем мелкие части, чтобы не плодить огрызки
    chunks = []
    for num, ls in parts:
        text = "\n".join(ls)
        if chunks and len(chunks[-1][2]) < MIN_PART and len(chunks[-1][2]) + len(text) <= MAX_LEN:
            chunks[-1][1] = num or chunks[-1][1]
            chunks[-1][2] += "\n" + text
        else:
            chunks.append([num, num, text])

    result = []
    for first, last, text in chunks:
        label = first if first == last else first + "-" + last
        if len(text) <= MAX_LEN:
            result.append((label, text))
            continue
        # одна часть сама по себе огромная (длинные перечни) - режем по строкам
        pieces = pack_lines(text.split("\n"))
        for i, piece in enumerate(pieces, 1):
            result.append(((label + "/" if label else "") + str(i), piece))
    return result


def pack_lines(lines):
    pieces = [""]
    for line in lines:
        if pieces[-1] and len(pieces[-1]) + len(line) > MAX_LEN:
            pieces.append("")
        pieces[-1] += ("\n" if pieces[-1] else "") + line
    return pieces


def article_units(law, text):
    units = []
    for num, title, lines in split_articles(text):
        body = "\n".join(lines)
        if len(body) < 80 and "утратил" in (title + body).lower():
            continue
        if len(body) <= MAX_LEN:
            units.append(make_unit(law, num, "", title, body))
            continue
        pieces = split_long(lines)
        if len(pieces) == 1 and not pieces[0][0].endswith("/1"):
            units.append(make_unit(law, num, "", title, body))
            continue
        for label, part_text in pieces:
            units.append(make_unit(law, num, label, title, part_text))
    return units


def point_units(law, text):
    """Нумерованные пункты; заголовком пункта служит раздел, в котором он стоит"""
    units = []
    section = ""
    point = None   # [номер, [строки], раздел]
    started = False

    def flush():
        if point:
            units.append(make_unit(law, point[0], "", point[2], "\n".join(point[1])))

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            flush()
            point = None
            section = line[3:]
            started = True
            continue
        if not started:
            continue
        m = POINT_RE.match(line)
        if m and (point is None or int(m.group(1)) == int(point[0]) + 1):
            flush()
            point = [m.group(1), [line], section]
        elif point:
            point[1].append(line)
    flush()
    return units


def plenum_units(text):
    return point_units("plenum17", text)


def section_text(text, start, end=None):
    """Кусок текста от раздела "## start..." до раздела "## end..." (не включая)"""
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("## " + start))
    last = len(lines)
    if end:
        last = next(i for i, l in enumerate(lines) if i > first and l.startswith("## " + end))
    return "\n".join(lines[first:last])


def list_units(law, article, title, text):
    """Перечень без смысла резать по пунктам: один-два куска текста"""
    pieces = pack_lines([l.strip() for l in text.splitlines() if l.strip()])
    parts = [str(i) for i in range(1, len(pieces) + 1)] if len(pieces) > 1 else [""]
    return [make_unit(law, article, part, title, piece) for part, piece in zip(parts, pieces)]


def list_body(text):
    # у перечня в начале шапка "Утвержден постановлением ..." и заголовок капсом, до первого пункта
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("1. "))
    return "\n".join(lines[first:])


def rules_units(text):
    rules = section_text(text, "Правила продажи товаров по договору", "Перечень товаров длительного")
    units = point_units("pp657", rules)
    remont = section_text(text, "Перечень товаров длительного", "Перечень непродовольственных")
    obmen = section_text(text, "Перечень непродовольственных")
    units += list_units("pp657", "remont", "Перечень товаров длительного пользования, на которые не распространяется требование о предоставлении товара на период ремонта или замены", list_body(remont))
    units += list_units("pp657", "obmen", "Перечень непродовольственных товаров надлежащего качества, не подлежащих обмену", list_body(obmen))
    return units


def complex_goods_units(text):
    body = list_body(section_text(text, "Перечень технически сложных товаров"))
    return list_units("pp924", "perechen", "Перечень технически сложных товаров", body)


def file_units(code, text):
    if code == "plenum17":
        return plenum_units(text)
    if code == "pp657":
        return rules_units(text)
    if code == "pp924":
        return complex_goods_units(text)
    return article_units(code, text)


def make_unit(law, article, part, title, text):
    uid = law + ":" + article + (":" + part if part else "")
    return {"id": uid, "law": law, "article": article, "part": part, "title": title, "text": text}


# --- ссылки между статьями ---

ART_REF = re.compile(
    r"(?:стать(?:я|и|е|ю|ей|ями|ях)|ст\.)\s*"
    r"((?:\d+(?:\.\d+)*)(?:\s*(?:,|и|-|–)\s*\d+(?:\.\d+)*)*)"
)
NUM_RE = re.compile(r"\d+(?:\.\d+)*")


def target_law(own_law, tail):
    tail = tail[:60]
    if re.match(r"\s*(ГПК|АПК|УК|НК|СК|ЖК|УПК|ЗК)\b", tail) or re.match(r"\s*Гражданск\w+ процессуальн", tail):
        return None
    if re.match(r"\s*КоАП", tail):
        return "koap"
    if re.match(r"\s*(ГК\b|Гражданск)", tail):
        return "gk"
    if re.match(r"\s*(ТК\b|Трудов)", tail):
        return "tk"
    if re.match(r"\s*(настоящего|данного)\s+(Закона|Кодекса)", tail):
        return own_law
    if re.match(r"\s*Закона (Российской Федерации )?(о|\"О|«О) защите прав потребителей", tail):
        return "zozpp"
    if own_law == "plenum17":
        # в постановлении "статья N Закона" - это ЗоЗПП, а "(статья 13)" без названия - тоже
        return "zozpp" if re.match(r"\s*(Закона\b|[),;.])", tail) else None
    # без уточнения: своя статья, если дальше не название другого акта
    if re.match(r"\s*[А-ЯЁ]", tail):
        return None
    return own_law


def expand_numbers(text):
    """"8 - 12" -> 8..12 (только целые номера, небольшой диапазон), остальное как есть"""
    nums = []
    for m in re.finditer(r"(\d+(?:\.\d+)*)(?:\s*[-–]\s*(\d+(?:\.\d+)*))?", text):
        a, b = m.group(1), m.group(2)
        if b and a.isdigit() and b.isdigit() and 0 < int(b) - int(a) <= 10:
            nums += [str(n) for n in range(int(a), int(b) + 1)]
        else:
            nums += [a] + ([b] if b else [])
    return nums


def find_refs(law, text):
    found = []
    for m in ART_REF.finditer(text):
        to_law = target_law(law, text[m.end():])
        if not to_law:
            continue
        for num in expand_numbers(m.group(1)):
            found.append((to_law, num))
    return found


# Перечни, которые закон поручает утвердить Правительству, и санкции КоАП к нормам, которые они защищают.
# В тексте номеров статей нет, связи проверены по смыслу вручную.
LINKS = [
    ("zozpp:18", "pp924:perechen"),    # "Перечень технически сложных товаров утверждается Правительством"
    ("zozpp:25", "pp657:obmen"),       # перечень товаров, не подлежащих обмену
    ("zozpp:20", "pp657:remont"),      # перечень товаров длительного пользования
    ("koap:14.15", "pp657:1"),         # нарушение правил продажи отдельных видов товаров
    ("koap:14.8", "zozpp:10"),         # информация о товаре
    ("koap:14.8", "zozpp:16"),         # условия, ущемляющие права потребителя
    ("koap:14.7", "zozpp:10"),
    ("koap:14.4", "zozpp:4"),          # качество товара
    ("koap:5.27", "tk:67"),            # оформление трудового договора
    ("koap:5.27", "tk:236"),           # невыплата заработной платы
    ("koap:5.27", "tk:419"),           # ответственность за нарушение трудового законодательства
]


def edge_type(from_law, to_law):
    # пункт Пленума разъясняет статью закона или кодекса
    if from_law == "plenum17" and to_law in ("zozpp", "gk"):
        return "explains"
    return "refers_to"


def build_refs(units):
    """-> отсортированный список (откуда, куда, тип); узлы - "закон:статья" """
    known = {(u["law"], u["article"]) for u in units}
    edges = set()
    for u in units:
        for to_law, num in find_refs(u["law"], u["text"]):
            if (to_law, num) not in known:
                continue
            if (to_law, num) == (u["law"], u["article"]):
                continue
            edges.add((u["law"] + ":" + u["article"], to_law + ":" + num, edge_type(u["law"], to_law)))
    for a, b in LINKS:
        if all(tuple(x.split(":")) in known for x in (a, b)):
            edges.add((a, b, "refers_to"))
    return sorted(edges)


def main():
    units = []
    for code in LAW_FILES:
        units += file_units(code, (RAW / (code + ".txt")).read_text(encoding="utf-8"))

    with open(CHUNKS, "w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    edges = build_refs(units)
    with open(REFS, "w", encoding="utf-8") as f:
        for a, b, kind in edges:
            f.write(json.dumps({"from": a, "to": b, "type": kind}, ensure_ascii=False) + "\n")

    counts = {}
    for u in units:
        counts[u["law"]] = counts.get(u["law"], 0) + 1
    by_type = {}
    for _, _, kind in edges:
        by_type[kind] = by_type.get(kind, 0) + 1
    print("единиц:", counts, "ссылок:", len(edges), by_type)


if __name__ == "__main__":
    main()
