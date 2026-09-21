#!/usr/bin/env python3
"""
search_media.py — поиск публикаций по инфоповоду без браузера.

Источники (включаются автоматически, если доступны):
  • Google News RSS      — без ключей, всегда; фильтр по дате «за N дней».
  • DuckDuckGo (html)    — без ключей; при частых запросах DDG временно блокирует (пропускается).
  • Google Custom Search — если заданы GOOGLE_CSE_KEY и GOOGLE_CSE_CX (100 запросов/день бесплатно).
  • Yandex Search API    — если заданы YANDEX_SEARCH_API_KEY и YANDEX_SEARCH_FOLDER_ID (Yandex Cloud).
  • Telegram watchlist   — публичные превью t.me/s/<канал> для каналов из project.json, без ключей.

Новые ссылки складываются в candidates.json проекта (дубли и уже учтённые отсекаются
по seen.json). Дальше кандидатов разбирает Claude: fetch_page.py → add_entry.py.

    python3 search_media.py <slug|project.json> [--days 30] [--sources news,ddg,cse,yandex,tg] [--dry-run]

Переменные окружения читаются также из ~/.gord-monitoring/.env (KEY=VALUE построчно).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitoring_lib import HOME, State, channel_of, domain_of, load_project, normalize_url  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def load_env() -> None:
    env = HOME / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def http_get(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def excluded(url: str, cfg: dict) -> bool:
    d = domain_of(url)
    for x in cfg.get("exclude_domains", []):
        if d == x or d.endswith("." + x):
            return True
    return False


# ---------------------------------------------------------------- Google News RSS

def google_news(query: str, days: int, lang: str = "ru") -> list[dict]:
    q = f"{query} when:{days}d"
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
           + f"&hl={lang}&gl=RU&ceid=RU:{lang}")
    out = []
    try:
        root = ET.fromstring(http_get(url))
    except Exception as e:  # noqa: BLE001
        print(f"  ! Google News RSS: {e}", file=sys.stderr)
        return out
    for item in root.iter("item"):
        title = html.unescape(item.findtext("title") or "")
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        src = item.find("source")
        source = (src.text if src is not None else "") or ""
        try:
            date = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").date().isoformat()
        except Exception:  # noqa: BLE001
            date = ""
        out.append({"url": link, "title": title, "source": source, "date": date, "via": "google-news", "query": query})
    return out


def resolve_google_news_link(link: str) -> str:
    """news.google.com/rss/articles/<id> → реальный URL статьи (через внутренний batchexecute Google News)."""
    if "news.google.com" not in link:
        return link
    m = re.search(r"/articles/([^?/]+)", link)
    if not m:
        return link
    art_id = m.group(1)
    try:
        page = http_get(f"https://news.google.com/articles/{art_id}", headers={"Accept-Language": "ru"}).decode("utf-8", "ignore")
        sg = re.search(r'data-n-a-sg="([^"]+)"', page); ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sg and ts):
            return link
        payload = json.dumps([[["Fbv4je", json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "RU:ru", None, 1, None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], art_id, int(ts.group(1)), sg.group(1)]), None, "generic"]]])
        raw = http_get("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                       headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Referer": "https://news.google.com/"},
                       data=("f.req=" + urllib.parse.quote(payload)).encode())
        text = raw.decode("utf-8", "ignore")
        chunk = text.split("\n\n")[1] if "\n\n" in text else text.lstrip(")]}'\n")
        parsed = json.loads(chunk)
        for item in parsed:
            if isinstance(item, list) and len(item) > 2 and isinstance(item[2], str) and item[2].startswith("["):
                inner = json.loads(item[2])
                if len(inner) > 1 and isinstance(inner[1], str) and inner[1].startswith("http"):
                    return inner[1]
        m2 = re.search(r'https?:\\?/\\?/(?!news\.google)[^"\\\s]+', text)
        if m2:
            return m2.group(0).replace("\\/", "/")
    except Exception as e:  # noqa: BLE001
        print(f"  ! decode google news link: {e}", file=sys.stderr)
    return link


# ---------------------------------------------------------------- DuckDuckGo (без ключей, индекс Bing)

def duckduckgo(query: str, days: int) -> list[dict]:
    df = "d" if days <= 1 else "w" if days <= 7 else "m" if days <= 31 else "y"
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "df": df, "kl": "ru-ru"})
    out = []
    try:
        page = http_get(url).decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"  ! DuckDuckGo: {e}", file=sys.stderr)
        return out
    if "anomaly-modal" in page or "result__a" not in page and "no-results" not in page:
        print("  ! DuckDuckGo временно блокирует автоматические запросы (anomaly) — источник пропущен, попробуй позже или добавь ключи Google CSE / Yandex", file=sys.stderr)
        return out
    for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(m.group(1))
        if "duckduckgo.com/l/?" in href:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = q.get("uddg", [href])[0]
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        snippet = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        out.append({"url": href, "title": title, "source": domain_of(href), "date": "", "snippet": snippet, "via": "duckduckgo", "query": query})
    return out


# ---------------------------------------------------------------- Google Custom Search

def google_cse(query: str, days: int) -> list[dict]:
    key, cx = os.environ.get("GOOGLE_CSE_KEY"), os.environ.get("GOOGLE_CSE_CX")
    if not (key and cx):
        return []
    out = []
    for start in (1, 11):
        params = {"key": key, "cx": cx, "q": query, "dateRestrict": f"d{days}", "num": 10, "start": start,
                  "lr": "lang_ru", "sort": "date"}
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(http_get(url))
        except urllib.error.HTTPError as e:
            print(f"  ! Google CSE HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001
            print(f"  ! Google CSE: {e}", file=sys.stderr)
            break
        for it in data.get("items", []):
            meta = (it.get("pagemap", {}).get("metatags") or [{}])[0]
            date = (meta.get("article:published_time") or meta.get("og:updated_time") or "")[:10]
            out.append({"url": it["link"], "title": it.get("title", ""), "source": it.get("displayLink", ""),
                        "date": date, "snippet": it.get("snippet", ""), "via": "google-cse", "query": query})
        if len(data.get("items", [])) < 10:
            break
    return out


# ---------------------------------------------------------------- Yandex Search API (Yandex Cloud)

def yandex_search(query: str, days: int) -> list[dict]:
    key, folder = os.environ.get("YANDEX_SEARCH_API_KEY"), os.environ.get("YANDEX_SEARCH_FOLDER_ID")
    if not (key and folder):
        return []
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    body = {
        "query": {"searchType": "SEARCH_TYPE_RU", "queryText": f"{query} date:>{since}", "familyMode": "FAMILY_MODE_NONE"},
        "sortSpec": {"sortMode": "SORT_MODE_BY_TIME", "sortOrder": "SORT_ORDER_DESC"},
        "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": 30, "docsInGroup": 1},
        "folderId": folder, "responseFormat": "FORMAT_XML", "userAgent": UA,
    }
    out = []
    try:
        raw = http_get("https://searchapi.api.cloud.yandex.net/v2/web/search",
                       headers={"Authorization": f"Api-Key {key}", "Content-Type": "application/json"},
                       data=json.dumps(body).encode())
        xml_bytes = base64.b64decode(json.loads(raw)["rawData"])
        root = ET.fromstring(xml_bytes)
    except urllib.error.HTTPError as e:
        print(f"  ! Yandex Search API HTTP {e.code}: {e.read()[:300]!r}", file=sys.stderr)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  ! Yandex Search API: {e}", file=sys.stderr)
        return out
    for doc in root.iter("doc"):
        url = doc.findtext("url") or ""
        title = "".join(doc.find("title").itertext()) if doc.find("title") is not None else ""
        mod = doc.findtext("modtime") or ""
        date = f"{mod[:4]}-{mod[4:6]}-{mod[6:8]}" if len(mod) >= 8 else ""
        out.append({"url": url, "title": html.unescape(title), "source": doc.findtext("domain") or "",
                    "date": date, "via": "yandex", "query": query})
    return out


# ---------------------------------------------------------------- Telegram: публичные превью каналов

def telegram_channel_posts(channel: str, keywords: list[str], days: int) -> list[dict]:
    channel = channel.strip().lstrip("@").split("/")[-1]
    url = f"https://t.me/s/{channel}"
    out = []
    try:
        page = http_get(url).decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"  ! t.me/s/{channel}: {e}", file=sys.stderr)
        return out
    since = dt.date.today() - dt.timedelta(days=days)
    for m in re.finditer(r'<div class="tgme_widget_message_wrap.*?(?=<div class="tgme_widget_message_wrap|$)', page, re.S):
        block = m.group(0)
        link = re.search(r'data-post="([^"]+)"', block)
        text = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        date = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        views = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', block)
        if not link:
            continue
        plain = html.unescape(re.sub(r"<[^>]+>", " ", text.group(1) if text else ""))
        plain = re.sub(r"\s+", " ", plain).strip()
        d = date.group(1)[:10] if date else ""
        if d and dt.date.fromisoformat(d) < since:
            continue
        low = plain.lower()
        if not any(k.lower() in low for k in keywords):
            continue
        out.append({"url": "https://t.me/" + link.group(1), "title": plain[:160], "source": channel, "date": d,
                    "views": (views.group(1) if views else ""), "via": "tg-watchlist", "query": channel})
    return out


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="slug проекта или путь к project.json")
    ap.add_argument("--days", type=int, help="глубина поиска в днях (по умолчанию из project.json или 30)")
    ap.add_argument("--sources", default="news,ddg,cse,yandex,tg", help="через запятую: news,ddg,cse,yandex,tg")
    ap.add_argument("--dry-run", action="store_true", help="показать найденное, ничего не сохранять")
    a = ap.parse_args(argv)
    load_env()
    slug, cfg = load_project(a.project)
    days = a.days or cfg.get("days", 30)
    sources = {s.strip() for s in a.sources.split(",")}
    queries = cfg.get("queries") or [cfg["project"]]
    keywords = cfg.get("keywords") or queries
    state = State(slug)

    found: list[dict] = []
    for q in queries:
        print(f"→ «{q}»")
        if "news" in sources:
            r = google_news(q, days); print(f"   Google News RSS: {len(r)}"); found += r
        if "ddg" in sources:
            r = duckduckgo(q, days); print(f"   DuckDuckGo: {len(r)}"); found += r
        if "cse" in sources:
            r = google_cse(q, days); print(f"   Google CSE: {len(r)}" if r else "   Google CSE: пропуск (нет ключей или пусто)"); found += r
        if "yandex" in sources:
            r = yandex_search(q, days); print(f"   Yandex: {len(r)}" if r else "   Yandex: пропуск (нет ключей или пусто)"); found += r
        time.sleep(0.5)
    if "tg" in sources:
        for ch in cfg.get("telegram_watchlist", []):
            r = telegram_channel_posts(ch, keywords, days); print(f"   t.me/s/{ch.lstrip('@')}: {len(r)}"); found += r
            time.sleep(0.7)

    new = 0
    dedup: dict[str, dict] = {}
    for c in found:
        c["url"] = resolve_google_news_link(c["url"]) if c["via"] == "google-news" else c["url"]
        c["url"] = normalize_url(c["url"])
        if excluded(c["url"], cfg):
            continue
        c["channel"] = channel_of(c["url"])
        dedup.setdefault(c["url"], c)
    for c in dedup.values():
        already = state.is_seen(c["url"])
        mark = "·" if already else "+"
        print(f" {mark} [{c['channel']}] {c.get('date') or '????-??-??'}  {c['url']}\n      {c.get('title', '')[:110]}")
        if not already and not a.dry_run:
            state.add_candidate(c); new += 1
    if not a.dry_run:
        state.save()
    print(f"\nИтого: найдено {len(dedup)}, новых кандидатов {new}. Кандидаты: {state.dir / 'candidates.json'}")


if __name__ == "__main__":
    main()
