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

ARTICLE_RE = re.compile(r"^Статья (\d+(?:\.\d+)?)\.\s*(.*)$")
PART_RE = re.compile(r"^(\d+)\.\s")
POINT_RE = re.compile(r"^(\d+)\.\s")

PLENUM_TITLE = "Постановление Пленума ВС РФ от 28.06.2012 N 17"


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


def plenum_units(text):
    units = []
    section = ""
    point = None   # [номер, [строки]]
    started = False

    def flush():
        if point:
            units.append(make_unit("plenum17", point[0], "", point[2], "\n".join(point[1])))

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


def make_unit(law, article, part, title, text):
    uid = law + ":" + article + (":" + part if part else "")
    return {"id": uid, "law": law, "article": article, "part": part, "title": title, "text": text}


# --- ссылки между статьями ---

ART_REF = re.compile(
    r"(?:стать(?:я|и|е|ю|ей|ями|ях)|ст\.)\s*"
    r"((?:\d+(?:\.\d+)?)(?:\s*(?:,|и|-|–)\s*\d+(?:\.\d+)?)*)"
)
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def target_law(own_law, tail):
    tail = tail[:60]
    if re.match(r"\s*(ГПК|АПК|УК|НК|КоАП|СК|ЖК|УПК|ЗК)\b", tail):
        return None
    if re.match(r"\s*(ГК\b|Гражданск)", tail):
        return "gk"
    if re.match(r"\s*(ТК\b|Трудов)", tail):
        return "tk"
    if re.match(r"\s*(настоящего|данного)\s+(Закона|Кодекса)", tail):
        return own_law
    if re.match(r"\s*Закона о защите прав потребителей", tail):
        return "zozpp"
    if own_law == "plenum17":
        # в постановлении "статья N Закона" - это ЗоЗПП
        return "zozpp" if re.match(r"\s*Закона\b", tail) else None
    # без уточнения: своя статья, если дальше не название другого акта
    if re.match(r"\s*[А-ЯЁ]", tail):
        return None
    return own_law


def find_refs(law, text):
    found = []
    for m in ART_REF.finditer(text):
        to_law = target_law(law, text[m.end():])
        if not to_law:
            continue
        for num in NUM_RE.findall(m.group(1)):
            found.append((to_law, num))
    return found


def build_refs(units):
    known = {(u["law"], u["article"]) for u in units}
    edges = set()
    for u in units:
        for to_law, num in find_refs(u["law"], u["text"]):
            if (to_law, num) not in known:
                continue
            if (to_law, num) == (u["law"], u["article"]):
                continue
            edges.add((u["law"] + ":" + u["article"], to_law + ":" + num))
    return sorted(edges)


def main():
    units = []
    for law in ["zozpp", "tk", "gk"]:
        units += article_units(law, (RAW / (law + ".txt")).read_text(encoding="utf-8"))
    units += plenum_units((RAW / "plenum17.txt").read_text(encoding="utf-8"))

    with open(CHUNKS, "w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    edges = build_refs(units)
    with open(REFS, "w", encoding="utf-8") as f:
        for a, b in edges:
            f.write(json.dumps({"from": a, "to": b}, ensure_ascii=False) + "\n")

    counts = {}
    for u in units:
        counts[u["law"]] = counts.get(u["law"], 0) + 1
    print("единиц:", counts, "ссылок:", len(edges))


if __name__ == "__main__":
    main()
