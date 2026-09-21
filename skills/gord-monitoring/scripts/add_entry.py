#!/usr/bin/env python3
"""
add_entry.py — внести публикацию в мониторинг (entries.json) или отклонить кандидата.

    # подтвердить публикацию (AVE/OTS подставятся из справочника площадок, если найдены)
    python3 add_entry.py <slug> --url https://... --format "экспертная статья" [--name gazeta.ru]
                         [--date 2026-09-05] [--ave 150000] [--ots 110300000] [--views 12300] [--note "..."]

    # отклонить кандидата (не про нас / дубль / реклама)
    python3 add_entry.py <slug> --reject https://... [--reason "не про инфоповод"]

    # пакетно из JSON: [{"url":..., "format":..., "name":..., "date":..., "ave":..., "ots":...}, ...]
    python3 add_entry.py <slug> --batch entries.json

    # показать всё, что учтено
    python3 add_entry.py <slug> --list
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitoring_lib import (State, channel_of, handle_of, load_project, load_reference,  # noqa: E402
                            lookup_reference, normalize_url, to_int)

FORMATS = ["экспертная статья", "моно-статья", "новость", "подборка", "дайджест", "упоминание",
           "пост", "сторис", "рилс", "видео", "конкурс"]


def add_one(state: State, item: dict, reference: list[dict]) -> dict:
    url = normalize_url(item["url"])
    cand = state.pop_candidate(url) or {}
    ch = item.get("channel") or channel_of(url)
    name = item.get("name") or cand.get("source") or handle_of(url)
    ref = lookup_reference(url, name, reference)
    if ref and not item.get("name") and ref.get("name"):
        name = ref["name"]
    entry = {
        "url": url,
        "channel": ch,
        "name": name,
        "format": item.get("format") or "",
        "date": item.get("date") or cand.get("date") or dt.date.today().isoformat(),
        "ave": to_int(item.get("ave")) if item.get("ave") not in (None, "") else (to_int(ref["ave"]) if ref else None),
        "ots": to_int(item.get("ots")) if item.get("ots") not in (None, "") else (to_int(ref["ots"]) if ref else None),
        "views": to_int(item.get("views")) or to_int(cand.get("views")),
        "title": item.get("title") or cand.get("title") or "",
        "query": cand.get("query") or item.get("query") or "",
        "via": cand.get("via") or item.get("via") or "manual",
        "note": item.get("note") or "",
        "added_at": dt.date.today().isoformat(),
    }
    if entry["ave"] is None or entry["ots"] is None:
        entry["note"] = (entry["note"] + " " if entry["note"] else "") + "[уточнить AVE/OTS: площадки нет в справочнике]"
    # если такая ссылка уже есть — обновляем, не дублируем
    for i, e in enumerate(state.entries):
        if e["url"] == url:
            state.entries[i] = {**e, **{k: v for k, v in entry.items() if v not in (None, "")}}
            state.seen[url] = "entry"
            return state.entries[i]
    state.entries.append(entry)
    state.seen[url] = "entry"
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--url"); ap.add_argument("--format"); ap.add_argument("--name"); ap.add_argument("--date")
    ap.add_argument("--ave"); ap.add_argument("--ots"); ap.add_argument("--views"); ap.add_argument("--note")
    ap.add_argument("--title"); ap.add_argument("--channel", choices=["сми", "тг", "инст", "тикток"])
    ap.add_argument("--reject"); ap.add_argument("--reason", default="")
    ap.add_argument("--batch"); ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    slug, cfg = load_project(a.project)
    state = State(slug)
    reference = load_reference()

    if a.list:
        for e in sorted(state.entries, key=lambda x: x.get("date", "")):
            print(f"{e['date']}  [{e['channel']}] {e['name']:28} {e['format']:20} AVE={e['ave']} OTS={e['ots']}  {e['url']}")
        print(f"\nВсего: {len(state.entries)} публикаций, кандидатов в очереди: {len(state.candidates)}")
        return
    if a.reject:
        url = normalize_url(a.reject)
        state.pop_candidate(url)
        state.seen[url] = "rejected: " + a.reason
        state.save()
        print(f"Отклонено: {url}")
        return
    items = []
    if a.batch:
        items = json.loads(Path(a.batch).read_text(encoding="utf-8"))
    elif a.url:
        if not a.format:
            ap.error(f"--format обязателен; варианты: {', '.join(FORMATS)}")
        items = [{k: v for k, v in vars(a).items() if k in ("url", "format", "name", "date", "ave", "ots", "views", "note", "title", "channel") and v}]
    else:
        ap.error("нужен --url, --reject, --batch или --list")
    for it in items:
        e = add_one(state, it, reference)
        flag = "  ⚠ нет AVE/OTS" if (e["ave"] is None or e["ots"] is None) else ""
        print(f"+ [{e['channel']}] {e['name']} · {e['format']} · {e['date']} · AVE={e['ave']} OTS={e['ots']}{flag}\n  {e['url']}")
    state.save()
    print(f"\nУчтено: {len(state.entries)}; кандидатов осталось: {len(state.candidates)}")


if __name__ == "__main__":
    main()
