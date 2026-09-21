"""
monitoring_lib.py — общие функции навыка gord-monitoring: пути, состояние проекта,
нормализация ссылок, справочник площадок (AVE / OTS).

Данные проекта живут вне репозитория: ~/.gord-monitoring/<slug>/
    project.json     — конфиг проекта (инфоповод, запросы, watchlist'ы)
    entries.json     — подтверждённые публикации (источник правды для таблицы)
    candidates.json  — найденные, но ещё не разобранные ссылки
    seen.json        — все ссылки, которые уже видели (в т.ч. отклонённые)
Переопределить корень: переменная окружения GORD_MONITORING_HOME.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
ASSETS = SKILL_DIR / "assets"
HOME = Path(os.environ.get("GORD_MONITORING_HOME", Path.home() / ".gord-monitoring"))

CHANNELS = ("сми", "тг", "инст", "тикток")
MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
             "сентябрь", "октябрь", "ноябрь", "декабрь"]

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                   "ysclid", "igsh", "igshid", "fbclid", "gclid", "yclid", "from", "_openstat",
                   "utm_referrer", "ref", "share_to_id"}


# ---------------------------------------------------------------- проект и состояние

def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", name).strip("-").lower()
    return s or "project"


def project_dir(slug: str) -> Path:
    d = HOME / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_project(slug_or_path: str) -> tuple[str, dict]:
    """Принимает slug проекта или путь к JSON. Возвращает (slug, конфиг)."""
    p = Path(slug_or_path)
    if p.suffix == ".json" and p.exists():
        cfg = json.loads(p.read_text(encoding="utf-8"))
        slug = cfg.get("slug") or slugify(cfg["project"])
        save_json(project_dir(slug) / "project.json", cfg)   # копия в домашнюю папку
        return slug, cfg
    slug = slug_or_path
    cfg_path = project_dir(slug) / "project.json"
    if not cfg_path.exists():
        raise SystemExit(f"Проект «{slug}» не найден: нет {cfg_path}. Создай project.json (см. examples/yoomoota.json).")
    return slug, load_json(cfg_path, {})


class State:
    def __init__(self, slug: str):
        self.dir = project_dir(slug)
        self.entries: list[dict] = load_json(self.dir / "entries.json", [])
        self.candidates: list[dict] = load_json(self.dir / "candidates.json", [])
        self.seen: dict[str, str] = load_json(self.dir / "seen.json", {})   # url -> статус

    def save(self) -> None:
        save_json(self.dir / "entries.json", self.entries)
        save_json(self.dir / "candidates.json", self.candidates)
        save_json(self.dir / "seen.json", self.seen)

    def is_seen(self, url: str) -> bool:
        return normalize_url(url) in self.seen

    def add_candidate(self, cand: dict) -> bool:
        url = normalize_url(cand["url"])
        if url in self.seen:
            return False
        cand["url"] = url
        cand.setdefault("found_at", dt.date.today().isoformat())
        self.candidates.append(cand)
        self.seen[url] = "candidate"
        return True

    def pop_candidate(self, url: str) -> dict | None:
        url = normalize_url(url)
        for i, c in enumerate(self.candidates):
            if c["url"] == url:
                return self.candidates.pop(i)
        return None


# ---------------------------------------------------------------- ссылки

def normalize_url(url: str) -> str:
    """Убираем трекинг-параметры и хвосты; путь и amp оставляем как есть (партнёр вставляет ссылку как найдена)."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    path = p.path or "/"
    if path != "/" and path.endswith("/") and "t.me" not in p.netloc:
        path = path.rstrip("/")
    return urlunparse((p.scheme, p.netloc.lower(), path, "", urlencode(q), ""))


def domain_of(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return re.sub(r"^(www|m|amp|mobile)\.", "", d)


def channel_of(url: str) -> str:
    d = domain_of(url)
    if d in ("t.me", "telegram.me") or d.endswith(".t.me"):
        return "тг"
    if "instagram.com" in d:
        return "инст"
    if "tiktok.com" in d:
        return "тикток"
    return "сми"


def handle_of(url: str) -> str:
    """Хэндл канала/аккаунта для соцсетей, домен для СМИ."""
    ch = channel_of(url)
    p = [x for x in urlparse(url).path.split("/") if x]
    if ch == "тг":
        if p and p[0] == "s":
            p = p[1:]
        return p[0] if p else ""
    if ch == "инст":
        if p and p[0] in ("p", "reel", "reels", "explore"):
            return ""
        if p and p[0] == "stories" and len(p) > 1:
            return p[1]
        return p[0] if p else ""
    if ch == "тикток":
        return p[0].lstrip("@") if p and p[0].startswith("@") else ""
    return domain_of(url)


# ---------------------------------------------------------------- справочник AVE / OTS

def load_reference(extra: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    for path in (ASSETS / "media-reference.csv", extra, HOME / "media-reference.csv"):
        if path and Path(path).exists():
            with open(path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def lookup_reference(url: str, name: str = "", reference: list[dict] | None = None) -> dict | None:
    """Ищем площадку по домену/хэндлу (точнее) или по имени. Поздние записи (домашний CSV) важнее."""
    reference = reference if reference is not None else load_reference()
    ch = channel_of(url)
    key = handle_of(url).lower()
    best = None
    for r in reference:
        if r.get("channel") != ch:
            continue
        rk = r.get("key", "").lower()
        if key and (rk == key or (ch == "сми" and key.endswith("." + rk))):
            best = r
        elif name and r.get("name", "").lower() == name.lower() and best is None:
            best = r
    return best


def to_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(" ", "").replace(" ", "")))
    except ValueError:
        return None


def month_label(date_str: str) -> str:
    try:
        d = dt.date.fromisoformat(date_str[:10])
    except Exception:
        return "без даты"
    return f"{MONTHS_RU[d.month - 1].capitalize()} {d.year}"
