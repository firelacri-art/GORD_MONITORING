#!/usr/bin/env python3
"""
import_candidates.py — внести в очередь кандидатов результаты, собранные в браузере
(Google, Яндекс, Instagram, TikTok, Telegram Web и т.д.).

Вход — JSON-список объектов {url, title, date, via, query, views} (поля кроме url
необязательны). Дата может быть как в выдаче: «29 авг. 2026 г.», «1 сентября»,
«2 недели назад», «вчера», «19 часов» — конвертируется в ISO. Дубли и уже учтённые
ссылки отсекаются по seen.json, свои домены — по exclude_domains проекта.

    python3 import_candidates.py <slug> results.json --via google-browser --query "аукцион Yoomoota"
    cat results.json | python3 import_candidates.py <slug> - --via yandex-browser
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitoring_lib import State, channel_of, domain_of, load_project, normalize_url  # noqa: E402

MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8,
          "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
          "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
SKIP_DOMAINS = ("google.", "yandex.", "ya.ru", "bing.com", "duckduckgo.com", "facebook.com/login", "accounts.")


def parse_ru_date(s: str, today: dt.date | None = None) -> str:
    """«29 авг. 2026 г.» / «1 сентября» / «2 недели назад» / «вчера» / «19 часов» / ISO → ISO или ''."""
    today = today or dt.date.today()
    s = (s or "").strip().lower().replace(" ", " ")
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if "сегодня" in s or re.match(r"\d+\s*(час|мин)", s):
        return today.isoformat()
    if "вчера" in s:
        return (today - dt.timedelta(days=1)).isoformat()
    m = re.match(r"(\d+)\s*(дн|дня|день|нед|мес)", s)
    if m:
        n = int(m.group(1)); unit = m.group(2)
        delta = n if unit.startswith("д") else n * 7 if unit.startswith("н") else n * 30
        return (today - dt.timedelta(days=delta)).isoformat()
    m = re.match(r"(\d{1,2})\s+([а-яёa-z]+)\.?\s*(\d{4})?", s)
    if m:
        mon = MONTHS.get(m.group(2)[:3])
        if mon:
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = dt.date(year, mon, int(m.group(1)))
            except ValueError:
                return ""
            if not m.group(3) and d > today:   # «30 декабря» в январе — прошлый год
                d = d.replace(year=year - 1)
            return d.isoformat()
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project"); ap.add_argument("file", help="JSON-файл или - для stdin")
    ap.add_argument("--via", default="browser", help="источник: google-browser, yandex-browser, instagram, tiktok, telegram-web…")
    ap.add_argument("--query", default="")
    ap.add_argument("--days", type=int, help="отбросить результаты старше N дней (если дата известна)")
    a = ap.parse_args(argv)
    slug, cfg = load_project(a.project)
    raw = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    items = json.loads(raw)
    if isinstance(items, dict):
        items = items.get("results") or items.get("items") or []
    state = State(slug)
    since = (dt.date.today() - dt.timedelta(days=a.days)).isoformat() if a.days else ""
    added = skipped = 0
    for it in items:
        url = (it.get("url") or it.get("u") or "").strip()
        if not url.startswith("http") or any(x in url for x in SKIP_DOMAINS):
            continue
        url = normalize_url(url)
        d = domain_of(url)
        if any(d == x or d.endswith("." + x) for x in cfg.get("exclude_domains", [])):
            continue
        date = parse_ru_date(it.get("date") or it.get("d") or "")
        if since and date and date < since:
            skipped += 1; continue
        cand = {"url": url, "title": (it.get("title") or it.get("t") or "").strip(), "date": date,
                "source": d, "channel": channel_of(url), "via": it.get("via") or a.via,
                "query": it.get("query") or a.query, "views": it.get("views", "")}
        if state.add_candidate(cand):
            added += 1; print(f" + [{cand['channel']}] {date or '????-??-??'}  {url}\n      {cand['title'][:100]}")
        else:
            skipped += 1
    state.save()
    print(f"\nДобавлено кандидатов: {added}; пропущено (дубли/старые/свои): {skipped}. Очередь: {len(state.candidates)}")


if __name__ == "__main__":
    main()
