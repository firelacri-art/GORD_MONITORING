---
name: gord-monitoring
description: Мониторинг публикаций об инфоповоде для PR-агентства GORD — СМИ через Google/Яндекс/Google News/DuckDuckGo, Telegram (публичные каналы и Telegram Web), Instagram и TikTok через залогиненный браузер пользователя. Находит новые упоминания, отсеивает дубли и уже учтённое, определяет формат (экспертная статья, упоминание, подборка, пост, сторис…), подставляет AVE и OTS из справочника площадок и собирает лист «Мониторинг публикаций» в стиле GORD (xlsx + CSV для Google-таблицы). Используй всегда, когда просят найти публикации, упоминания, выходы, охваты, мониторинг СМИ/соцсетей, «кто написал про…», «обнови мониторинг», «сколько публикаций вышло по…», AVE/OTS по проекту, а также при запуске по расписанию. Аргумент — slug проекта или название инфоповода.
---

# Мониторинг публикаций GORD

Что делает вручную менеджер: вбивает инфоповод в Google и Яндекс с фильтром по дате,
ищет по названию в Telegram, собирает сторис и посты блогеров, вносит в таблицу
«Название · Ссылка · Формат · AVE · OTS». Навык делает то же, но каждый день,
без дублей и с таблицей на выходе. Данные живут в `~/.gord-monitoring/<slug>/`.

## Порядок работы

### 0. Проект

`$ARGUMENTS` — slug (`yoomoota`) или название инфоповода. Если `~/.gord-monitoring/<slug>/project.json`
нет — создай по образцу [scripts/examples/yoomoota.json](scripts/examples/yoomoota.json):
`project`, `slug`, `queries` (3–5 формулировок: бренд латиницей и кириллицей, «бренд +
событие», «бренд + площадка»), `keywords`, `days`, `exclude_domains` (сайты клиента и
агентства), `telegram_watchlist`, `instagram_watchlist`, `brand_accounts`, `sheet_url`.
Спроси только то, чего нет в запросе; остальное заполни сам и покажи конфиг.

### 1. Поиск без браузера (всегда)

```bash
pip install -q openpyxl Pillow        # один раз
python3 ${CLAUDE_SKILL_DIR}/scripts/search_media.py <slug> [--days 30]
```

Источники подключаются сами: Google News RSS и DuckDuckGo без ключей; Google CSE и
Яндекс, если в `~/.gord-monitoring/.env` есть ключи (как получить —
[references/search-apis.md](references/search-apis.md)); Telegram-каналы из watchlist
через публичные превью `t.me/s/…`. Новое попадает в `candidates.json`, уже виденное
отсекается.

### 2. Браузерные каналы (если есть инструменты браузера и пользователь залогинен)

Instagram (отметки бренда, watchlist блогеров, сторис, поиск), TikTok (поиск с фильтром
по дате, watchlist), Telegram Web (вкладка «Публикации» при Premium; TGStat при
подписке), Яндекс/Google в браузере, если нет ключей API. Процедуры и лимиты темпа —
[references/browser-channels.md](references/browser-channels.md). Правила: не больше
15–25 страниц на сервис за прогон, паузы, ничего не лайкать и не писать; капча или
просьба войти → остановиться и сообщить. Найденное вноси сразу через `add_entry.py`.

### 3. Разбор кандидатов

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/fetch_page.py --candidates <slug> --limit 15
```

По каждому: есть ли упоминание инфоповода (не однофамильцы, не другой проект бренда,
не собственный сайт клиента), дата в периоде, формат по правилам из
[references/ave-ots.md](references/ave-ots.md). Решения:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/add_entry.py <slug> --url URL --format "экспертная статья" --date 2026-09-05 [--name gazeta.ru] [--views N] [--note "…"]
python3 ${CLAUDE_SKILL_DIR}/scripts/add_entry.py <slug> --reject URL --reason "не про инфоповод"
```

AVE и OTS подставляются из справочника площадок автоматически; если площадки нет —
поле остаётся пустым с пометкой «уточнить». **Цифры не выдумывать.** Сомнительные
кандидаты не отклонять молча: оставить в очереди и перечислить в сводке.

### 4. Таблица

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_monitoring_sheet.py <slug> ["Мониторинг публикаций — Проект.xlsx"] --csv new-rows.csv
```

Лист в стиле GORD: логотип, красная линейка, шапка, месяцы и подсекции СМИ / Telegram /
Instagram / TikTok, ИТОГО по AVE и OTS. Ссылка — голый URL в ячейке, не слово «ссылка».
Google-таблица партнёра обновляется вставкой строк из CSV или импортом xlsx новым листом
([references/scheduling.md](references/scheduling.md), раздел «Куда попадает результат»);
через браузер с Google-аккаунтом Claude может вставить строки сам, спросив подтверждение.

### 5. Сводка

Коротко: период, сколько новых публикаций по каналам, сумма AVE и OTS за период, список
«уточнить AVE/OTS», список сомнительных кандидатов с одной строкой почему, что не
проверялось (нет ключей, нет браузера, капча). Файл таблицы — приложить.

## Правила

- Один инфоповод = один проект = один `entries.json`. Не смешивать проекты клиента.
- Ссылка сохраняется как найдена (AMP-версия допустима), без `utm`, `ysclid`, `igsh`.
- Дата — дата публикации, не дата находки. Если на странице даты нет — из выдачи;
  если и там нет — сегодняшняя с пометкой в комментарии.
- Собственные каналы клиента и агентства в мониторинг не попадают (`exclude_domains`,
  `brand_accounts` — только как источник отметок).
- Соцсети через браузер — только с аккаунта пользователя и только в темпе человека.
  Никаких обходов капчи, входов, кодов подтверждения.
- Перед повторным запуском не сбрасывать `seen.json`: смысл навыка в накоплении.

## Справочные материалы

- [references/search-apis.md](references/search-apis.md) — источники, ключи Google CSE и Yandex Search API, `.env`.
- [references/browser-channels.md](references/browser-channels.md) — Instagram, Telegram Web, TikTok, Яндекс/Google через браузер.
- [references/ave-ots.md](references/ave-ots.md) — форматы публикаций, справочник AVE/OTS, что делать с неизвестной площадкой.
- [references/scheduling.md](references/scheduling.md) — команда, планировщик, облачные routines, выгрузка в Google-таблицу.
- `scripts/`: `search_media.py`, `fetch_page.py`, `add_entry.py`, `build_monitoring_sheet.py`, `monitoring_lib.py`; пример проекта `examples/yoomoota.json`.
- `assets/media-reference.csv` — стартовый справочник площадок (≈90 записей из мониторингов агентства); `assets/gord-logo.png`.
