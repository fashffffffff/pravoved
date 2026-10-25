"""Чистка итогового текста: служебные метки, повторы."""
import re

UNCONFIRMED = " [не подтверждено источниками]"
# модель иногда сама пишет такие метки вместо ссылки
TOOL_MARK = re.compile(r"\s*\[(?:инструмент|расчёт|расчет|калькулятор)[^\]]*\]", re.IGNORECASE)
ARTICLE_BEFORE = re.compile(r"((?:ст\.|стать\w+)\s*\d+(?:\.\d+)*(?:\s*(?:ГК|ТК|КоАП|ЗоЗПП)(?:\s*РФ)?)?)$", re.IGNORECASE)


def strip_marks(text):
    """-> (текст без меток, какие упоминания не подтвердились)"""
    names = []
    for m in re.finditer(re.escape(UNCONFIRMED), text):
        found = ARTICLE_BEFORE.search(text[max(0, m.start() - 40):m.start()])
        if found and found.group(1) not in names:
            names.append(found.group(1))
    text = text.replace(UNCONFIRMED, "")
    text = TOOL_MARK.sub("", text)
    return text, names


def norm(line):
    line = re.sub(r"\[[^\]]*\]", "", line)
    line = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line)
    return re.sub(r"[\W_]+", " ", line.lower()).strip()


def drop_repeats(text):
    """Убирает строки и предложения, которые уже были выше (модель иногда дублирует абзацы)"""
    seen = set()
    out = []
    for line in text.split("\n"):
        key = norm(line)
        if line.strip() and not key:
            continue
        # короткие строки (заголовки, «Что делать:») повторять можно
        if len(key) < 40:
            out.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        line = drop_sentence_repeats(line, seen)
        # от строки остался один маркер списка
        if norm(line):
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def drop_sentence_repeats(line, seen):
    # маркер списка («1.», «*») не считаем предложением
    prefix = re.match(r"\s*(?:\d+[.)]|[-*•])?\s*", line).group(0)
    parts = re.split(r"(?<=[.!?])\s+", line[len(prefix):])
    if len(parts) < 2:
        return line
    keep = []
    for p in parts:
        key = norm(p)
        if len(key) >= 40 and key in seen:
            continue
        seen.add(key)
        keep.append(p)
    return prefix + " ".join(keep)
