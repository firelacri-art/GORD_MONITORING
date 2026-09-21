# GORD Monitoring — навык Claude Code для мониторинга публикаций

Навык (skill) для [Claude Code](https://claude.ai/code): находит публикации об инфоповоде
в **СМИ, Telegram, Instagram и TikTok**, отсеивает дубли, определяет формат, подставляет
AVE и OTS из справочника площадок и собирает лист **«Мониторинг публикаций» в стиле
GORD** (xlsx + CSV для Google-таблицы). Заменяет ручной цикл «Google и Яндекс с фильтром
по дате → поиск в Telegram → сторис блогеров → таблица».

Пара к навыку таблиц [firelacri-art/GORD_TABLES](https://github.com/firelacri-art/GORD_TABLES);
методология агентства — [kofyonerook210/GORD_PR_AGENCY](https://github.com/kofyonerook210/GORD_PR_AGENCY).

## Установка (1 минута)

```
/plugin marketplace add firelacri-art/GORD_MONITORING
/plugin install gord-monitoring@gord-monitoring
```

Зависимости Python: `pip install openpyxl Pillow`.
Без плагина: `git clone https://github.com/firelacri-art/GORD_MONITORING.git && ./GORD_MONITORING/install.sh`
(копирует навык в `~/.claude/skills`; с `--project` — в `.claude/skills` текущего проекта).

## Запуск

```
/gord-monitoring:gord-monitoring yoomoota
```

или фразой: «проверь публикации по аукциону Yoomoota за месяц», «обнови мониторинг
Моремании». Первый запуск создаёт конфиг проекта `~/.gord-monitoring/<slug>/project.json`
(инфоповод, варианты запросов, каналы и блогеры для наблюдения). Пример —
[skills/gord-monitoring/scripts/examples/yoomoota.json](skills/gord-monitoring/scripts/examples/yoomoota.json).

По расписанию: планировщик приложения Claude Code или облачные routines (`/schedule`) —
см. [scheduling.md](skills/gord-monitoring/references/scheduling.md).

## Что откуда берётся

| Канал | Как | Что нужно |
| --- | --- | --- |
| СМИ | Google News RSS + DuckDuckGo сразу; Google Custom Search и Yandex Search API при наличии ключей | ключи по желанию, инструкция в [search-apis.md](skills/gord-monitoring/references/search-apis.md) |
| Telegram-каналы из списка наблюдения | публичные превью `t.me/s/канал`: текст, дата, просмотры | ничего |
| Telegram глобальный поиск | Telegram Web в браузере пользователя (вкладка «Публикации» при Premium) или TGStat | залогиненный браузер, Premium или TGStat |
| Instagram | отметки бренда, профили и сторис блогеров из списка, поиск по словам и хэштегам — через браузер пользователя | залогиненный браузер (из РФ — VPN) |
| TikTok | поиск с фильтром по дате и профили авторов — через браузер | браузер, вход желателен |

Браузерные каналы работают через расширение «Claude in Chrome» или встроенный браузер
Claude Code, где пользователь уже вошёл в аккаунты. Навык не вводит пароли, не проходит
капчи, ничего не лайкает и не пишет; листает в темпе человека (до 15–25 страниц на сервис
за прогон). Просмотр сторис виден автору как просмотр с аккаунта агентства.

## Результат

- `~/.gord-monitoring/<slug>/entries.json` — все подтверждённые публикации (накапливаются).
- `Мониторинг публикаций — <проект>.xlsx` — лист в стиле GORD: логотип, шапка,
  разбивка по месяцам и каналам, ИТОГО по AVE и OTS; ссылка в ячейке как обычный URL.
- CSV с новыми строками — для вставки в существующую Google-таблицу агентства.
- Сводка в чат: новые публикации, суммы, что уточнить.

Справочник площадок с AVE/OTS (≈90 записей из мониторингов агентства) —
[media-reference.csv](skills/gord-monitoring/assets/media-reference.csv); свои дополнения
кладутся в `~/.gord-monitoring/media-reference.csv` и имеют приоритет.

## Ручной запуск скриптов

```bash
S=skills/gord-monitoring/scripts
python3 $S/search_media.py $S/examples/yoomoota.json --days 30     # поиск → candidates.json
python3 $S/fetch_page.py --candidates yoomoota --limit 10           # что внутри найденных страниц
python3 $S/add_entry.py yoomoota --url URL --format "новость" --date 2026-09-05
python3 $S/add_entry.py yoomoota --reject URL --reason "не про нас"
python3 $S/build_monitoring_sheet.py yoomoota out.xlsx --csv new.csv
```

## Структура

```
GORD_MONITORING/
├── .claude-plugin/plugin.json, marketplace.json
├── skills/gord-monitoring/
│   ├── SKILL.md                      # инструкция для Claude
│   ├── references/                   # search-apis, browser-channels, ave-ots, scheduling
│   ├── scripts/                      # search_media, fetch_page, add_entry, build_monitoring_sheet, monitoring_lib
│   ├── scripts/examples/yoomoota.json
│   ├── assets/                       # gord-logo.png, media-reference.csv
│   └── vendor/build_gord_table.py    # генератор стиля из GORD_TABLES
├── install.sh, requirements.txt, LICENSE
```

## Лицензия

Код — MIT. Логотип GORD Agency принадлежит агентству и включён для оформления его документов.
