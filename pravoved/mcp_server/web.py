import ipaddress
import os
from urllib.parse import urlparse

import httpx
import trafilatura

MAX_PAGE_BYTES = 2_000_000
MAX_TEXT = 6000
USER_AGENT = "Mozilla/5.0 (compatible; Pravoved/0.1; +local legal assistant)"

# чем выше в списке, тем больше доверия; поддомены считаются тем же сайтом
TRUST_DOMAINS = {
    "official": ["pravo.gov.ru", "publication.pravo.gov.ru", "kremlin.ru", "government.ru", "vsrf.ru", "ksrf.ru",
                 "consultant.ru", "garant.ru"],
    "authority": ["rospotrebnadzor.ru", "rostrud.gov.ru", "xn--80akibcicpdbetz7e2g.xn--p1ai", "cbr.ru",
                  "nalog.gov.ru", "sfr.gov.ru", "gosuslugi.ru"],
    "draft": ["sozd.duma.gov.ru", "regulation.gov.ru", "duma.gov.ru"],
}
TRUST_ORDER = ["official", "authority", "draft", "unverified"]


def host_of(url):
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        return host.encode("idna").decode()
    except UnicodeError:
        return host


def trust_of(url):
    host = host_of(url)
    for level, domains in TRUST_DOMAINS.items():
        for d in domains:
            if host == d or host.endswith("." + d):
                return level
    return "unverified"


def trust_rank(item):
    return TRUST_ORDER.index(item["trust"])


def search_ddg(query, n):
    from ddgs import DDGS
    rows = DDGS().text(query, region="ru-ru", max_results=n)
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in rows]


def search_searxng(base, query, n):
    r = httpx.get(base.rstrip("/") + "/search", params={"q": query, "format": "json", "language": "ru-RU"},
                  timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    rows = r.json().get("results", [])[:n]
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")} for x in rows]


def search(query, max_results=6):
    base = os.environ.get("SEARXNG_URL")
    rows = search_searxng(base, query, max_results) if base else search_ddg(query, max_results)
    results = [dict(r, trust=trust_of(r["url"])) for r in rows if r["url"]]
    # официальные сайты вперёд, порядок поисковика внутри уровня сохраняется
    return sorted(results, key=trust_rank)


def is_private(url):
    host = urlparse(url).hostname or ""
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def download(url):
    with httpx.stream("GET", url, timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        data = b""
        for chunk in r.iter_bytes():
            data += chunk
            if len(data) > MAX_PAGE_BYTES:
                break
        return data[:MAX_PAGE_BYTES].decode(r.encoding or "utf-8", errors="replace")


def read(url):
    if urlparse(url).scheme not in ("http", "https") or is_private(url):
        return {"url": url, "error": "адрес не подходит"}
    try:
        html = download(url)
    except httpx.HTTPError as e:
        return {"url": url, "error": "не удалось загрузить: %s" % e}
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(html)
    return {
        "url": url,
        "title": (meta.title if meta else None) or "",
        "trust": trust_of(url),
        "date": (meta.date if meta else None) or None,
        "text": text[:MAX_TEXT],
    }
