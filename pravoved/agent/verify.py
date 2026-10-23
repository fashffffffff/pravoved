import re

from pravoved.retrieval.search import get_article

MARKER = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
ARTICLE = re.compile(r"(?:\bст\.|\bстать[яиеёю]|\bстатьёй)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def article_numbers(text):
    return set(ARTICLE.findall(text))


def check_citations(answer, sources, tool_text=""):
    """sources - список Hit в том порядке, как они пронумерованы в промпте.
    Возвращает (текст без неверных ссылок, cited, invalid, номера использованных источников)."""
    cited = 0
    invalid = 0
    used = []

    def fix_marker(m):
        nonlocal cited, invalid
        good = []
        for n in re.findall(r"\d+", m.group(1)):
            cited += 1
            if 1 <= int(n) <= len(sources):
                good.append(n)
                if int(n) not in used:
                    used.append(int(n))
            else:
                invalid += 1
        return "[%s]" % ", ".join(good) if good else ""

    text = MARKER.sub(fix_marker, answer)

    # статьи по номеру: должны быть в найденных источниках (или в ответе инструмента) и существовать в базе
    allowed = {s.article for s in sources if get_article(s.law, s.article)}
    allowed |= article_numbers(tool_text)

    def fix_article(m):
        nonlocal cited, invalid
        cited += 1
        if m.group(1) in allowed:
            return m.group(0)
        invalid += 1
        return m.group(0) + " [не подтверждено источниками]"

    text = ARTICLE.sub(fix_article, text)
    text = re.sub(r"[ \t]+([.,;])", r"\1", text)
    return text, cited, invalid, sorted(used)
