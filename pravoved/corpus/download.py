"""Скачивает тексты законов с consultant.ru и сохраняет чистый текст в data/raw."""
import json
import re
import sys
import time
from datetime import date
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
    "koap": ("34661", "articles"),
    # ПП №2463 с 01.09.2026 заменено постановлением от 30.05.2026 №657 (2463 помечено утратившим силу)
    "pp657": ("535649", "sections"),
    "pp924": ("121597", "sections"),
}

# какие статьи ГК берём: гл. 30 §1-2, гл. 32, гл. 34, гл. 35, гл. 42 §1
GK_RANGES = [(454, 505), (572, 582), (606, 688), (807, 818)]

# из КоАП нужны только статьи про штрафы продавцов и работодателей
KOAP_ARTICLES = {"5.27", "5.27.1", "14.4", "14.5", "14.7", "14.8", "14.15"}


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


def last_change(html):
    """Самая поздняя дата из пометок "(в ред. ...)" на странице, ISO. Нужна, когда в заголовке редакции нет"""
    soup = BeautifulSoup(html, "lxml")
    found = []
    for tag in soup.select(".doc-edit, .doc-insert"):
        for d, m, y in re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", tag.get_text(" ")):
            found.append(y + "-" + m + "-" + d)
    return max(found) if found else ""


def clean_title_line(line):
    # на странице заголовок вида "ТК РФ Статья 236. ..." / "Закон о ЗПП Статья 18. ..."
    return re.sub(r"^.*?(?=Статья \d)", "", line)


def article_links(toc_html, law_id):
    pat = r'href="(/document/cons_doc_LAW_%s/[0-9a-f]{40}/)"[^>]*>\s*Статья (\d+(?:\.\d+)*)\.' % law_id
    links = {}
    for url, num in re.findall(pat, toc_html):
        links.setdefault(num, url)
    return links


def want_article(code, num):
    if code == "koap":
        return num in KOAP_ARTICLES
    if code != "gk":
        return True
    main = int(num.split(".")[0])
    return any(a <= main <= b for a, b in GK_RANGES)


def edition_of(html):
    """Строка вида "ред. от 28.12.2025, с изм. от 17.02.2026" из заголовка документа"""
    h1 = BeautifulSoup(html, "lxml").find("h1")
    title = " ".join(h1.get_text(" ").split()) if h1 else ""
    m = re.search(r"\(((?:ред\.|с изм\.)[^)]*)\)", title)
    return m.group(1) if m else ""


def download_articles(code, law_id):
    toc = get(BASE + law_id + "/")
    edition = edition_of(toc)
    links = article_links(toc, law_id)
    blocks = []
    latest = ""
    for num, url in links.items():
        if not want_article(code, num):
            continue
        html = get("https://www.consultant.ru" + url)
        latest = max(latest, last_change(html))
        lines = paragraphs(html)
        if not lines:
            print("пусто:", code, num)
            continue
        lines[0] = clean_title_line(lines[0])
        blocks.append("\n".join(lines))
        time.sleep(0.15)
    if not edition and latest:
        edition = "последняя поправка в тексте от " + latest
    return "\n\n".join(blocks), edition


def download_sections(law_id):
    first = get(BASE + law_id + "/")
    edition = edition_of(first)
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
    return "\n".join(lines), edition


def main(only=None, out=RAW):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    for code, (law_id, mode) in LAWS.items():
        if only and code not in only:
            continue
        print("качаю", code)
        if mode == "sections":
            text, edition = download_sections(law_id)
        else:
            text, edition = download_articles(code, law_id)
        (out / (code + ".txt")).write_text(text + "\n", encoding="utf-8")
        meta[code] = {
            "url": BASE + law_id + "/",
            "edition": edition,
            "downloaded": date.today().isoformat(),
        }
        print(code, len(text), "символов,", edition or "редакция не найдена")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
