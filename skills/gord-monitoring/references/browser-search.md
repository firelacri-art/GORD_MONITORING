# Поиск в Google и Яндексе через браузер пользователя (без ключей API)

Основной способ поиска по СМИ, когда ключей нет. Работает **только в настоящем Chrome
пользователя** через расширение «Claude in Chrome» (`mcp__claude-in-chrome__*`): там есть
история, куки и аккаунт, поэтому Google и Яндекс отдают выдачу без капчи. Встроенная
панель браузера Claude Code (`mcp__Claude_Browser__*`) для Google не подходит: пустой
профиль сразу получает страницу `google.com/sorry` (капча). Проверено 21.09.2026.

Ничего вводить руками не нужно: страница открывается по URL с параметрами, результаты
снимаются одним JS-вызовом, потом импортируются в очередь кандидатов.

## Порядок на один запрос

1. `tabs_context_mcp` → одна вкладка на весь прогон (`tabs_create_mcp`, в конце закрыть).
2. `navigate` на URL из таблицы ниже → `computer wait 2–3 с`.
3. `javascript_tool` со сниппетом → получаем JSON-массив `{t,u,date}`.
4. Проверить флаг `captcha` в ответе: `true` → остановиться, скриншот пользователю, дальше
   не долбить. Google обычно даёт капчу после ~30–50 быстрых запросов; норма — 5–8 запросов
   на инфоповод с паузами 3–5 с.
5. Сохранить массив в файл и импортировать:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/import_candidates.py <slug> results.json --via google-browser --query "аукцион Yoomoota" --days 30
   ```
   Даты вида «29 авг. 2026 г.», «1 сентября», «2 недели назад», «вчера» конвертируются сами.
6. Вторая страница нужна, только если на первой все результаты релевантны:
   Google `&start=20`, Яндекс `&p=1`.

Все действия — `browser_batch`: navigate → wait → javascript_tool для 2–3 запросов подряд
в одном вызове.

## URL с фильтром по дате

| Что | URL | Период |
| --- | --- | --- |
| Google, веб | `https://www.google.com/search?q=<запрос>&tbs=qdr:m&hl=ru&num=20` | `qdr:d` сутки · `qdr:w` неделя · `qdr:m` месяц · `qdr:y` год |
| Google, новости | `https://www.google.com/search?q=<запрос>&tbm=nws&tbs=qdr:m&hl=ru` | те же коды |
| Яндекс, веб | `https://yandex.ru/search/?text=<запрос>&within=2&lr=213` | `within=77` сутки · `within=2` месяц (подпись фильтра «За месяц» проверена); для недели брать месяц и отсеять по дате через `--days 7` |
| Яндекс, новости | `https://dzen.ru/news/search?text=<запрос>` | без фильтра, дата в карточке |

`<запрос>` — URL-encoded. **Бренд брать в кавычки** (`"Yoomoota" Novikov`): без кавычек
Яндекс подбирает похожие слова и выдаёт мусор («аукцион» → автоаукционы). `lr=213` —
Москва; для региональных клиентов свой код региона.

Набор запросов на инфоповод: `"Бренд"`, `"Бренд" площадка`, `"Бренд" событие`,
кириллическое написание бренда. Google web + Google news + Яндекс web = 3 URL на запрос.

## JS-сниппеты (вставлять в `javascript_tool` как есть)

**Google, веб-выдача** (заголовок `h3` внутри ссылки, дата в сниппете):
```js
({captcha: /sorry\/index|unusual traffic|необычный трафик/i.test(location.href + document.body.innerText.slice(0,2000)),
  results: [...document.querySelectorAll('a h3')].map(h => {
    const a = h.closest('a'); const box = a.closest('div[data-hveid]') || a.parentElement.parentElement;
    const t = (box ? box.innerText : '').replace(/\s+/g, ' ');
    const d = t.match(/(\d{1,2}\s+[а-яё]+\.?\s+\d{4}\s*г?\.?|\d+\s+(дн|час|нед|мес)[а-яё.]*\s+назад|вчера|сегодня)/i);
    return {t: h.innerText, u: a.href, date: d ? d[0] : ''};
  })})
```

**Google, вкладка «Новости»** (карточки `a[href]` с `div[role=heading]`):
```js
({captcha: /sorry\/index|необычный трафик/i.test(location.href + document.body.innerText.slice(0,2000)),
  results: [...document.querySelectorAll('a[href^="http"]')].filter(a => a.querySelector('div[role="heading"]')).map(a => {
    const t = a.innerText.replace(/\s+/g, ' ');
    const d = t.match(/(\d{1,2}\s+[а-яё]+\.?\s+\d{4}\s*г?\.?|\d+\s+(дн|час|нед|мес)[а-яё.]*\s+назад|вчера)/i);
    return {t: a.querySelector('div[role="heading"]').innerText, u: a.href, date: d ? d[0] : ''};
  })})
```

**Яндекс, веб-выдача** (`li.serp-item`, первая внешняя ссылка, `h2`, дата в тексте):
```js
({captcha: /showcaptcha|SmartCaptcha|не робот/i.test(location.href + document.body.innerText.slice(0,2000)),
  results: [...document.querySelectorAll('li.serp-item')].map(li => {
    const a = [...li.querySelectorAll('a[href^="http"]')].find(x => !/yandex\.|ya\.ru|dzen\.ru\/news/.test(x.hostname + x.pathname));
    const h = li.querySelector('h2'); const t = li.innerText.replace(/\s+/g, ' ');
    const d = t.match(/(\d{1,2}\s+[а-яё]+\s+\d{4}|\d{1,2}\s+[а-яё]{3,8}(?=\s)|вчера|сегодня|\d+\s+(дн|час|нед|мес)[а-яё.]*\s+назад)/i);
    return a ? {t: h ? h.innerText : '', u: a.href, date: d ? d[0] : ''} : null;
  }).filter(Boolean)})
```

Ответ `javascript_tool` иногда прячет URL с параметрами как `[BLOCKED: Cookie/query
string data]` — это фильтр расширения. Такие ссылки открыть отдельно через `find` по
заголовку или взять без query-части: `u: a.href.split('?')[0]` в сниппете.

## Что делать с результатами

- Ссылки на Instagram/TikTok/Telegram из выдачи — это тоже кандидаты (`import_candidates.py`
  сам ставит канал по домену). Их содержимое проверяется в браузере по
  [browser-channels.md](browser-channels.md), не через `fetch_page.py`.
- Результаты без даты — не отбрасывать: дату возьмёт `fetch_page.py` со страницы.
- Собственные сайты клиента/агентства отсекаются `exclude_domains` из project.json.

## Эталонный прогон (Yoomoota, 21.09.2026)

Google `qdr:m` по «аукцион Yoomoota»: snob.ru, beautybackstage.ru, 6 постов и рилс в
Instagram. Яндекс `within=2` по `"Yoomoota" Novikov`: forklore.ru, afisha.ru, snob.ru,
peopletalk.ru, intro-mag.ru, beautybackstage.ru, weekend.rambler.ru, t.me/gord_agency.
Пересечение с ручным мониторингом партнёра полное, плюс 5 площадок, которых у них не было.
