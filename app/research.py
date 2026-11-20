"""Free web research for the agents: no API keys, no paid search.

* search  — DuckDuckGo HTML endpoint (free, no key); falls back to the Wikipedia API when it is unavailable.
  `official=True` restricts the search to official Kazakhstan sources (laws, the National Bank, gov.kz).
* read    — downloads one page and returns only the passages relevant to the question (saves tokens).

Guard rails: an agent only calls this when the local knowledge base is not enough (tool hint), at most
WEB_MAX_CALLS network calls per check, only public http(s) hosts (no internal addresses), and the query is a
general topic — never text from the client's TZ.

Caching (app.cache, persistent): search results live a day; pages live WEB_PAGE_TTL_DAYS (3) and are then
revalidated (ETag / Last-Modified / content hash). If a page really changed, the cached agent answers that
were built on it are dropped, so nobody keeps reasoning from an old edition of a law.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from . import cache
from .llm import meter

OFFICIAL = ["adilet.zan.kz", "nationalbank.kz", "gov.kz", "afm.gov.kz", "ardfm.kz"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; Specta-research/1.0)", "Accept-Language": "ru,en;q=0.8"}
SEARCH_TTL = 24 * 3600


def page_ttl() -> float:
    return float(os.getenv("WEB_PAGE_TTL_DAYS", "3")) * 86400


def enabled() -> bool:
    return os.getenv("WEB_RESEARCH", "1").lower() not in ("0", "false", "no", "off")


def max_calls() -> int:
    return int(os.getenv("WEB_MAX_CALLS", "6"))


def _spend() -> str | None:
    b = meter.get()          # the per-check usage meter also counts web calls
    if b is None:
        return None
    if b.get("web", 0) >= max_calls():
        return "лимит веб-запросов для этой проверки исчерпан — используй базу знаний"
    b["web"] = b.get("web", 0) + 1
    return None


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _public(url: str) -> bool:
    """Only public http(s) hosts — the agent must not reach internal services."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


async def _ddg(query: str) -> list[dict]:
    async with httpx.AsyncClient(headers=UA, timeout=10, follow_redirects=True) as c:
        r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
    r.raise_for_status()
    out = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=class="result__a"|$)', r.text, re.S):
        href, title, rest = m.groups()
        if "uddg=" in href:                               # DuckDuckGo redirect link → real URL
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if "duckduckgo.com/y.js" in href:                 # ads
            continue
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S)
        out.append({"title": _clean(title), "url": href, "snippet": _clean(snip.group(1))[:300] if snip else ""})
        if len(out) >= 5:
            break
    return out


async def _wiki(query: str) -> list[dict]:
    async with httpx.AsyncClient(headers=UA, timeout=10) as c:
        r = await c.get("https://ru.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 4})
    r.raise_for_status()
    return [{"title": x["title"], "url": "https://ru.wikipedia.org/wiki/" + x["title"].replace(" ", "_"),
             "snippet": _clean(x.get("snippet", ""))} for x in r.json().get("query", {}).get("search", [])]


async def search(query: str, official: bool = True) -> str:
    query = " ".join(query.split())[:200]
    key = f"{official}|{query.lower()}"
    if hit := cache.get("web_search", key):
        return hit[0]
    if err := _spend():
        return json.dumps({"error": err}, ensure_ascii=False)
    q = query + (" (" + " OR ".join(f"site:{d}" for d in OFFICIAL) + ")" if official else "")
    results, source = [], "duckduckgo"
    try:
        results = await _ddg(q)
        if not results and official:
            results = await _ddg(query)
    except (httpx.HTTPError, asyncio.TimeoutError):
        results = []
    if not results:
        source = "wikipedia"
        try:
            results = await _wiki(query)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
            results = []
    val = json.dumps({"source": source, "results": results} if results else {"note": "ничего не найдено"}, ensure_ascii=False)
    if results:
        cache.put("web_search", key, val, ttl=SEARCH_TTL)
    return val


def _text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<(br|p|div|li|tr|h\d)[^>]*>", "\n", page)
    return "\n".join(x for x in (" ".join(_clean(l).split()) for l in page.split("\n")) if len(x) > 40)


def _relevant(text: str, focus: str, limit: int = 3500) -> str:
    words = {w[:6] for w in re.findall(r"[а-яёa-z0-9]{4,}", focus.lower())}
    paras = text.split("\n")
    if not words:
        return text[:limit]
    scored = sorted(range(len(paras)), key=lambda i: -sum(w in paras[i].lower() for w in words))
    keep, size = [], 0
    for i in scored:
        if size > limit or not any(w in paras[i].lower() for w in words):
            break
        keep.append(i)
        size += len(paras[i])
    return "\n".join(paras[i] for i in sorted(keep))[:limit] or text[:limit]


def _plain(url: str) -> str:
    """The new adilet.zan.kz is a JS app; the same documents are served as plain HTML on old.adilet.zan.kz."""
    return re.sub(r"^https?://adilet\.zan\.kz/", "https://old.adilet.zan.kz/", url)


def page_dep(url: str) -> str:
    """The cache key of a page — also the dependency name of the agent answers that read it."""
    return _plain(url.strip()).split("#")[0]


async def _fetch(url: str, meta: dict | None = None) -> tuple[int, str, dict]:
    """(status, text, meta). With `meta` it is a conditional request: 304 = unchanged."""
    headers = dict(UA)
    if meta and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta and meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    async with httpx.AsyncClient(headers=headers, timeout=12, follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code == 304:
        return 304, "", {}
    r.raise_for_status()
    ctype = r.headers.get("content-type", "html")
    if "html" not in ctype and "text" not in ctype:
        raise ValueError("это не текстовая страница")
    body = r.text[:2_000_000]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    text = _text(body)
    return r.status_code, text, {"url": str(r.url), "title": _clean(title.group(1)) if title else "",
                                 "etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified"),
                                 "hash": cache.key_of(text)[:16], "checked": time.time()}


async def page(url: str) -> tuple[str, dict, str]:
    """(text, meta, how) where how = fresh | cached | revalidated | changed | stale."""
    dep = page_dep(url)
    if hit := cache.get("web_page", dep):
        return hit[0], hit[1], "cached"
    old = cache.get("web_page", dep, allow_expired=True)
    if err := _spend():
        if old:
            return old[0], old[1], "stale"
        raise RuntimeError(err)
    try:
        status, text, meta = await _fetch(dep, old[1] if old else None)
    except (httpx.HTTPError, ValueError) as e:
        if old:                                   # source is down: use the old copy, but say so
            return old[0], old[1], "stale"
        raise RuntimeError(f"страница недоступна: {type(e).__name__}" if isinstance(e, httpx.HTTPError) else str(e))
    if status == 304 or (old and meta["hash"] == old[1].get("hash")):
        cache.extend("web_page", dep, page_ttl())
        return old[0], {**old[1], "checked": time.time()}, "revalidated"
    cache.put("web_page", dep, text, ttl=page_ttl(), meta=meta)
    if old:                                       # the page really changed → answers built on it are outdated
        cache.invalidate_dep(dep)
        return text, meta, "changed"
    return text, meta, "fresh"


NOTE = {"stale": "источник сейчас недоступен — это копия от {date}, перепроверь позже",
        "changed": "страница изменилась с прошлой проверки — это новая редакция",
        "revalidated": "перепроверено: страница не менялась"}


async def read(url: str, focus: str = "") -> str:
    url = page_dep(url)
    if not await asyncio.to_thread(_public, url):
        return json.dumps({"error": "можно открывать только публичные http(s)-страницы"}, ensure_ascii=False)
    try:
        text, meta, how = await page(url)
    except RuntimeError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    out = {"url": meta.get("url", url), "title": meta.get("title", ""), "text": _relevant(text, focus),
           "checked": time.strftime("%d.%m.%Y", time.localtime(meta.get("checked", time.time())))}
    if how in NOTE:
        out["note"] = NOTE[how].format(date=out["checked"])
    return json.dumps(out, ensure_ascii=False)
