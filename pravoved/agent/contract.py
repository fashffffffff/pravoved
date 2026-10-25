import re
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from pravoved.agent import prompts
from pravoved.agent.tools import call_tool
from pravoved.agent.graph import hit_key, parse_json, strip_think, usage_of
from pravoved.agent.verify import check_citations
from pravoved.retrieval.search import search

# номер пункта: 3.2 или 3. или 3)
NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)+[.)]?|\d+[.)])\s+(\S.*)$")
SKIP_SECTION = re.compile(r"реквизит|подпис|адреса сторон", re.IGNORECASE)
BOILERPLATE = re.compile(r"\bИНН\b|\bОГРН|\bБИК\b|р/с|паспорт\w*\s*(?:серии\s*)?\d|_{3,}|\bМ\.П\.", re.IGNORECASE)
MIN_CLAUSE = 25
BATCH_CLAUSES = 5
BATCH_CHARS = 1800
HITS_PER_CLAUSE = 5
MAX_HITS = 15
SNIPPET = 800

KINDS = {
    "rent": ("найма жилого помещения", "наниматель"),
    "labour": ("трудовой", "работник"),
    "consumer": ("с потребителем (купля-продажа или услуги)", "потребитель"),
}
KIND_WORDS = {
    "rent": re.compile(r"наймодател|нанимател|найм\w* жилого|аренд", re.IGNORECASE),
    "labour": re.compile(r"работодател|работник|трудов", re.IGNORECASE),
}
COLORS = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def is_heading(line):
    letters = [c for c in line if c.isalpha()]
    return len(letters) > 3 and line.upper() == line and len(line) < 70


def split_clauses(text):
    """Режет договор на пункты. -> список {id, text, section}"""
    clauses = []
    section = ""
    skip = False
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = NUMBERED.match(line)
        if m:
            num, rest = m.group(1).rstrip(".)"), m.group(2)
            if "." not in num and is_heading(rest):
                section, skip, current = rest, bool(SKIP_SECTION.search(rest)), None
                continue
            current = {"id": num, "text": rest, "section": section}
            if not skip:
                clauses.append(current)
        elif is_heading(line):
            section, skip, current = line, bool(SKIP_SECTION.search(line)), None
        elif current is not None:
            # продолжение пункта; текст до первого пункта (стороны, преамбула) в проверку не берём
            current["text"] += " " + line
    if not clauses:
        clauses = split_paragraphs(text)
    return [c for c in clauses if is_real_clause(c)]


def split_paragraphs(text):
    parts = [p.strip().replace("\n", " ") for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [{"id": "п%d" % i, "text": p, "section": ""} for i, p in enumerate(parts, 1)]


def is_real_clause(clause):
    t = clause["text"]
    if len(t) < MIN_CLAUSE:
        return False
    return not (len(t) < 150 and BOILERPLATE.search(t))


def contract_kind(text):
    rent = len(KIND_WORDS["rent"].findall(text))
    labour = len(KIND_WORDS["labour"].findall(text))
    if max(rent, labour) < 3:
        return "consumer"
    return "rent" if rent > labour else "labour"


def make_batches(clauses):
    batches, cur, size = [], [], 0
    for c in clauses:
        if cur and (len(cur) == BATCH_CLAUSES or size + len(c["text"]) > BATCH_CHARS):
            batches.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c["text"])
    if cur:
        batches.append(cur)
    return batches


def find_hits(batch):
    hits, seen = [], set()
    for c in batch:
        for h in search(c["text"][:400], k=HITS_PER_CLAUSE):
            if hit_key(h) not in seen:
                seen.add(hit_key(h))
                hits.append(h)
    return hits[:MAX_HITS]


def source_list(hits):
    return "\n\n".join("[%d] %s. %s\n%s" % (i, h.citation, h.title, h.text[:SNIPPET]) for i, h in enumerate(hits, 1))


def norm_color(value):
    v = str(value).lower()
    if "red" in v or "красн" in v or "🔴" in v:
        return "red"
    if "green" in v or "зелен" in v or "зелён" in v or "🟢" in v:
        return "green"
    return "yellow"


async def judge_batch(llm, batch, hits, kind):
    name, weak = KINDS[kind]
    system = prompts.CONTRACT_SYSTEM.format(kind=name, weak=weak)
    clauses = "\n".join("[%s] %s" % (c["id"], c["text"]) for c in batch)
    user = prompts.CONTRACT_USER.format(sources=source_list(hits), clauses=clauses)
    t = time.time()
    msg = await llm.ainvoke([SystemMessage(system), HumanMessage(user)])
    usage = usage_of(msg, time.time() - t)
    data = parse_json(strip_think(msg.content)) or {}
    items = data.get("clauses") if isinstance(data.get("clauses"), list) else []
    return {str(i.get("id")): i for i in items if isinstance(i, dict)}, usage


def finish_clause(clause, item, hits):
    """Проверяет ссылки в оценке модели и собирает итог по пункту"""
    if item is None:
        return {**clause, "color": "yellow", "reason": "Модель не оценила этот пункт, проверьте его сами.",
                "cites": [], "invalid": 0, "downgraded": False}
    color = norm_color(item.get("color"))
    text, cited, invalid, used = check_citations(str(item.get("reason") or ""), hits)
    cites = []
    for n in used:
        h = hits[n - 1]
        if (h.law, h.article) not in [(c["law"], c["article"]) for c in cites]:
            cites.append({"law": h.law, "article": h.article, "citation": h.citation,
                          "snippet": h.text[:200].replace("\n", " ")})
    reason = re.sub(r"\s*\[[\d,;\s]+\]", "", text).replace(" .", ".").strip()
    downgraded = False
    if color == "red" and not cites:
        # красный без подтверждённой статьи не выдаём
        color, downgraded = "yellow", True
        reason = (reason + " (нет подтверждающей статьи в базе)").strip()
    return {**clause, "color": color, "reason": reason, "cites": cites, "invalid": invalid, "downgraded": downgraded}


def summarize(results):
    counts = {c: sum(r["color"] == c for r in results) for c in COLORS}
    reds = [r for r in results if r["color"] == "red"]
    return counts, reds[:5]


async def check_contract(llm, text, on_progress=None):
    start = time.time()
    clauses = split_clauses(text)
    kind = contract_kind(text)
    results, usage = [], []
    batches = make_batches(clauses)
    for i, batch in enumerate(batches, 1):
        if on_progress:
            on_progress(i, len(batches))
        hits = find_hits(batch)
        try:
            items, u = await judge_batch(llm, batch, hits, kind)
            usage.append(u)
        except Exception:
            items = {}
        results += [finish_clause(c, items.get(c["id"]), hits) for c in batch]
    counts, top = summarize(results)
    res = {"kind": kind, "clauses": results, "counts": counts, "top_risks": top,
           "invalid": sum(r["invalid"] for r in results), "seconds": round(time.time() - start, 2), "usage": usage}
    res["markdown"] = to_markdown(res)
    return res


async def read_file(path, tools):
    """Текст договора из txt, docx, pdf или картинки. Сканы идут через инструмент read_scan."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".docx":
        from docx import Document
        return "\n".join(par.text for par in Document(str(p)).paragraphs)
    res = await call_tool(tools, "read_scan", {"path": str(p.resolve())})
    if "error" in res:
        raise ValueError(res["error"])
    return res["text"]


def clause_line(r):
    line = "%s **%s** %s" % (COLORS[r["color"]], r["id"], r["text"])
    if r["reason"]:
        line += "\n  - %s" % r["reason"]
    if r["cites"]:
        line += "\n  - Источники: " + "; ".join(c["citation"] for c in r["cites"])
    return line


def to_markdown(res):
    c = res["counts"]
    lines = ["Итого: 🔴 %d, 🟡 %d, 🟢 %d (пунктов: %d)" % (c["red"], c["yellow"], c["green"], len(res["clauses"])), ""]
    if res["top_risks"]:
        lines.append("Главные риски:")
        lines += ["- п. %s: %s" % (r["id"], r["reason"] or r["text"][:80]) for r in res["top_risks"]]
        lines.append("")
    lines += [clause_line(r) for r in res["clauses"] if r["color"] != "green"]
    lines += ["", "Остальные пункты (%d) в порядке." % c["green"]]
    return "\n".join(lines)
