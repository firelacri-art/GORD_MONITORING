#!/usr/bin/env python3
"""
fetch_page.py — открыть публикацию и показать, что в ней есть: заголовок, дата,
площадка, есть ли упоминание инфоповода, фрагменты текста вокруг ключевых слов.
Нужен Claude, чтобы решить: релевантно ли и какой формат (экспертная статья /
упоминание / новость / подборка / дайджест).

    python3 fetch_page.py <url> --keywords "Yoomoota" "аукцион Yoomoota" [--json]
    python3 fetch_page.py --candidates <slug> [--limit 10]   # прогнать всех кандидатов проекта
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitoring_lib import State, channel_of, domain_of, load_project  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self.in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            a = dict(attrs)
            key = a.get("property") or a.get("name") or ""
            if key and a.get("content"):
                self.meta[key.lower()] = a["content"]
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
        final = r.geturl()
        ctype = r.headers.get("Content-Type", "")
    enc = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        enc = m.group(1)
    text = raw.decode(enc, "ignore")
    p = TextExtractor()
    p.feed(text)
    body = html.unescape(re.sub(r"[ \t]+", " ", "".join(p.parts)))
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    return {"url": final, "title": html.unescape(p.title.strip()), "meta": p.meta, "text": body}


def analyze(url: str, keywords: list[str]) -> dict:
    try:
        page = fetch(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e), "channel": channel_of(url), "domain": domain_of(url)}
    text = page["text"]
    low = text.lower()
    hits = []
    for k in keywords:
        for m in re.finditer(re.escape(k.lower()), low):
            s, e = max(0, m.start() - 160), min(len(text), m.end() + 160)
            hits.append({"keyword": k, "context": re.sub(r"\s+", " ", text[s:e]).strip()})
            if len(hits) >= 6:
                break
    meta = page["meta"]
    date = (meta.get("article:published_time") or meta.get("og:updated_time") or meta.get("datepublished")
            or meta.get("date") or meta.get("pubdate") or "")[:10]
    words = len(re.findall(r"\w+", text))
    mention_share = round(sum(low.count(k.lower()) for k in keywords) / max(1, words) * 1000, 2)
    return {
        "url": page["url"], "channel": channel_of(url), "domain": domain_of(page["url"]),
        "title": page["title"] or meta.get("og:title", ""), "date": date,
        "site_name": meta.get("og:site_name", ""), "description": meta.get("og:description", "")[:300],
        "words": words, "keyword_hits": len(hits), "mentions_per_1000_words": mention_share,
        "contexts": hits, "lead": re.sub(r"\s+", " ", text[:500]),
        "hint": ("нет упоминания — проверь вручную или отклони" if not hits else
                 "упоминание есть; формат определи по доле текста об инфоповоде: "
                 "≥ половины текста → экспертная статья / моно-статья, абзац → упоминание, "
                 "список площадок/событий → подборка или дайджест, короткая заметка → новость"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?")
    ap.add_argument("--keywords", nargs="*", default=[])
    ap.add_argument("--candidates", help="slug проекта: разобрать кандидатов из candidates.json")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    results = []
    if a.candidates:
        slug, cfg = load_project(a.candidates)
        keywords = cfg.get("keywords") or cfg.get("queries") or [cfg["project"]]
        st = State(slug)
        for c in [x for x in st.candidates if x.get("channel", "сми") == "сми"][: a.limit]:
            results.append(analyze(c["url"], keywords))
    elif a.url:
        results.append(analyze(a.url, a.keywords or []))
    else:
        ap.error("укажи url или --candidates <slug>")

    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for r in results:
        print("=" * 100)
        print(f"{r['url']}\n[{r['channel']}] {r.get('domain')}  date={r.get('date') or '?'}  {r.get('site_name', '')}")
        if r.get("error"):
            print("  ошибка:", r["error"]); continue
        print("  title:", r["title"])
        print(f"  words={r['words']} hits={r['keyword_hits']} mentions/1000={r['mentions_per_1000_words']}")
        for h in r["contexts"][:4]:
            print(f"   … {h['context']} …")
        print("  →", r["hint"])


if __name__ == "__main__":
    main()
