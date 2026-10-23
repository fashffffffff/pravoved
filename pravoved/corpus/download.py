"""Скачивает тексты законов с consultant.ru и сохраняет чистый текст в data/raw."""
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.consultant.ru/document/cons_doc_LAW_"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# код -> (id документа на consultant, как качать)
# "articles" - по странице на статью, "sections" - преамбула + страницы разделов
LAWS = {
    "zozpp": ("305", "articles"),
    "plenum17": ("131885", "sections"),
    "tk": ("34683", "articles"),
    "gk": ("9027", "articles"),
}

# какие статьи ГК берём: гл. 30 §1-2, гл. 34, гл. 35
GK_RANGES = [(454, 505), (606, 688)]


def get(url):
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("не удалось скачать " + url)


def paragraphs(html):
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(".document-page__content") or soup
    # редакционные пометки консультанта: "(в ред. ...)", "см. текст в предыдущей редакции"
    for tag in body.select(".doc-edit, .doc-insert, .doc-roll"):
        tag.decompose()
    out = []
    for p in body.find_all("p"):
        text = " ".join(p.get_text(" ").split())
        text = re.sub(r"\s+([,.;:)])", r"\1", text)
        if text:
            out.append(text)
    return out


def clean_title_line(line):
    # на странице заголовок вида "ТК РФ Статья 236. ..." / "Закон о ЗПП Статья 18. ..."
    return re.sub(r"^.*?(?=Статья \d)", "", line)


def article_links(toc_html, law_id):
    pat = r'href="(/document/cons_doc_LAW_%s/[0-9a-f]{40}/)"[^>]*>\s*Статья (\d+(?:\.\d+)?)\.' % law_id
    links = {}
    for url, num in re.findall(pat, toc_html):
        links.setdefault(num, url)
    return links


def want_article(code, num):
    if code != "gk":
        return True
    main = int(num.split(".")[0])
    return any(a <= main <= b for a, b in GK_RANGES)


def download_articles(code, law_id):
    toc = get(BASE + law_id + "/")
    links = article_links(toc, law_id)
    blocks = []
    for num, url in links.items():
        if not want_article(code, num):
            continue
        lines = paragraphs(get("https://www.consultant.ru" + url))
        if not lines:
            print("пусто:", code, num)
            continue
        lines[0] = clean_title_line(lines[0])
        blocks.append("\n".join(lines))
        time.sleep(0.15)
    return "\n\n".join(blocks)


def download_sections(law_id):
    first = get(BASE + law_id + "/")
    lines = paragraphs(first)
    pat = r'href="(/document/cons_doc_LAW_%s/[0-9a-f]{40}/)"[^>]*>([^<]*)' % law_id
    sections = dict(re.findall(pat, first))
    for url, title in sections.items():
        part = paragraphs(get("https://www.consultant.ru" + url))
        title = " ".join(title.split())
        # заголовок раздела на странице идёт отдельными строками, заменяем его меткой
        while part and part[0] in title:
            part.pop(0)
        lines += ["## " + title] + part
        time.sleep(0.15)
    return "\n".join(lines)


def main(only=None):
    RAW.mkdir(parents=True, exist_ok=True)
    for code, (law_id, mode) in LAWS.items():
        if only and code not in only:
            continue
        print("качаю", code)
        if mode == "sections":
            text = download_sections(law_id)
        else:
            text = download_articles(code, law_id)
        (RAW / (code + ".txt")).write_text(text + "\n", encoding="utf-8")
        print(code, len(text), "символов")


if __name__ == "__main__":
    main(sys.argv[1:])
