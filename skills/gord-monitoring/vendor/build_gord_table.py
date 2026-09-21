#!/usr/bin/env python3
"""
build_gord_table.py — генератор Excel-таблиц в фирменном стиле GORD Agency.

Собирает .xlsx из JSON-спецификации: на каждом листе сверху логотип GORD,
красная линейка, заголовок листа, серая шапка таблицы, шрифт Geologica,
выпадающие списки статусов с цветовой подсветкой. Файл открывается в Excel
и без потерь импортируется в Google Таблицы (см. references/google-sheets.md).

Использование:
    python3 build_gord_table.py spec.json out.xlsx
    python3 build_gord_table.py --example event-project out.xlsx   # полный пример
    python3 build_gord_table.py --presets                           # список пресетов

Зависимости: openpyxl, Pillow (pip install openpyxl Pillow).
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

try:
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.page import PageMargins
except ImportError:  # pragma: no cover
    sys.exit("Нужен openpyxl: pip install openpyxl Pillow")

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
DEFAULT_LOGO = ASSETS / "gord-logo.png"

# ---------------------------------------------------------------------------
# Фирменные константы (см. references/gord-table-style.md)
# ---------------------------------------------------------------------------
FONT = "Geologica"            # корпоративный шрифт; в Google Sheets есть из коробки
FONT_FALLBACK = "Montserrat"  # если Geologica не установлена в Excel

RED = "D72410"        # Signal Clay — единственный акцент
BLACK = "000000"
DARK_GREY = "434343"  # рамки карточек на дашборде
GREY_HEADER = "F3F3F3"   # шапка таблицы
GREY_ZEBRA = "F3F3F3"    # чередование строк
GREY_TOTAL = "D9D9D9"    # строка ИТОГО
GREY_LINE = "D9D9D9"     # рамки пустых строк-заготовок
LINK_BLUE = "1155CC"

# Цвета статусов (палитра чипов Google Sheets)
STATUS_GREEN = ("D9EAD3", "274E13")
STATUS_YELLOW = ("FFF2CC", "7F6000")
STATUS_RED = ("F4CCCC", "990000")
STATUS_GREY = ("EFEFEF", "434343")

GREY_WORDS = ("не в работе", "не связались", "не начат", "план")
RED_WORDS = ("не оплачено", "не доставлено", "отмен", "отказ", "проблема", "срочно")
GREEN_WORDS = ("выполнено", "готово", "оплачено", "доставлено", "подтверд", "вышла", "done")
YELLOW_WORDS = ("в работе", "в процессе", "частично", "ожида", "перенес", "отправлен")

NUM_FMT = "#,##0"           # разрядка по локали: в русском Excel/Sheets — пробел (316 272 358)
DATE_FMT = "[$-419]dd.mm.yyyy"
DATE_LONG_FMT = "[$-419]d mmmm yyyy"

SIZE_TITLE = 14
SIZE_HEADER = 10
SIZE_BODY = 9
SIZE_DASH_TITLE = 13

COL_MARGIN = 2.29     # узкая колонка A (поле слева) и хвостовая колонка
COL_NUMBER = 5.86     # колонка №
ROW_LOGO = 50.25      # высота строки с логотипом
ROW_TITLE = 27.0
ROW_HEADER = 33.0
ROW_BODY = 15.0

LOGO_EMU = (838200, 419100)           # 0.92" × 0.46" — размер логотипа на рабочих листах
LOGO_EMU_DASH = (1190625, 600075)     # крупнее на дашборде / разборе проекта
EMU_PER_PX = 9525

# ---------------------------------------------------------------------------
# Пресеты листов (структура из эталонной таблицы «Novikov x Yoomoota»)
# ---------------------------------------------------------------------------
STATUS_WORK = ["не в работе", "в работе", "выполнено"]
STATUS_READY = ["Не в работе", "В работе", "Готово"]
STATUS_PAY = ["Не оплачено", "Оплачено", "Оплачено 3-м лицом, возместить оплату"]
STATUS_DELIVERY = ["Не доставлено", "В процессе доставки", "Доставлено"]

PRESETS: dict[str, dict] = {
    "dashboard": {
        "kind": "card",
        "name": "Дашборд проекта",
        "fields": ["Дата мероприятия", "PR-менеджер проекта", "Клиент", "Площадка", "Материалы"],
    },
    "budget": {
        "kind": "table",
        "name": "Смета",
        "title": "СМЕТА МЕРОПРИЯТИЯ",
        "numbered": False,
        "zebra": False,
        "columns": [
            {"header": "Позиция", "width": 48, "bold": False},
            {"header": "Кол-во / часы", "width": 18, "align": "center"},
            {"header": "Стоимость RUB с налогом", "width": 23, "align": "center", "format": NUM_FMT},
            {"header": "Стоимость RUB", "width": 18, "align": "center", "format": NUM_FMT},
            {"header": "Комментарий", "width": 50},
            {"header": "Статус оплаты", "width": 28, "status": STATUS_PAY},
        ],
        "total": {"label": "ИТОГО (с НДС)", "sum_columns": ["Стоимость RUB с налогом", "Стоимость RUB"]},
        "min_rows": 18,
    },
    "plan": {
        "kind": "table",
        "name": "План подготовки",
        "title": "План работы",
        "numbered": True,
        "zebra": True,
        "columns": [
            {"header": "Задача", "width": 60, "bold": True},
            {"header": "Дедлайн", "width": 22, "align": "center", "format": DATE_FMT},
            {"header": "Ответственный", "width": 32, "align": "center"},
            {"header": "Комментарии", "width": 35},
            {"header": "Статус", "width": 22, "status": STATUS_WORK},
        ],
        "min_rows": 20,
    },
    "contacts": {
        "kind": "table",
        "name": "Контакты",
        "title": "Контакты партнеров и подрядчиков",
        "numbered": True,
        "columns": [
            {"header": "Подрядчик / партнер", "width": 60, "bold": True},
            {"header": "Контакт", "width": 22, "align": "center"},
            {"header": "Ответственный", "width": 32, "align": "center"},
            {"header": "Комментарии", "width": 35},
        ],
        "min_rows": 15,
    },
    "logistics": {
        "kind": "table",
        "name": "Логистика",
        "title": "Логистика",
        "numbered": True,
        "columns": [
            {"header": "Что доставляем", "width": 60, "bold": True},
            {"header": "Контакт", "width": 22, "align": "center"},
            {"header": "Откуда", "width": 32},
            {"header": "Куда", "width": 35},
            {"header": "Дата и время", "width": 22, "align": "center", "format": "[$-419]dd.mm.yyyy hh:mm"},
            {"header": "Статус", "width": 24, "status": STATUS_DELIVERY},
        ],
        "min_rows": 15,
    },
    "timing": {
        "kind": "table",
        "name": "Тайминг",
        "title": "Тайминг мероприятия",
        "numbered": True,
        "columns": [
            {"header": "Действие", "width": 60},
            {"header": "Время", "width": 22, "align": "center", "format": "hh:mm"},
            {"header": "Ответственный", "width": 32, "align": "center"},
            {"header": "Статус", "width": 24, "status": STATUS_READY},
        ],
        "min_rows": 20,
    },
    "checklist": {
        "kind": "table",
        "name": "Чек-лист",
        "title": "Чек-лист",
        "numbered": True,
        "columns": [
            {"header": "Действие", "width": 60},
            {"header": "Ответственный", "width": 32, "align": "center"},
            {"header": "Статус", "width": 24, "status": STATUS_READY},
        ],
        "min_rows": 15,
    },
    "checklist-after": {
        "kind": "table",
        "name": "Чек-лист после ивента",
        "title": "Чек-лист пост-ивента",
        "numbered": True,
        "columns": [
            {"header": "Действие", "width": 60},
            {"header": "Ответственный", "width": 32, "align": "center"},
            {"header": "Дедлайн", "width": 22, "align": "center", "format": DATE_FMT},
            {"header": "Статус", "width": 24, "status": STATUS_READY},
        ],
        "min_rows": 15,
    },
    "guests": {
        "kind": "table",
        "name": "Гости",
        "title": "Гости мероприятия",
        "numbered": False,
        "columns": [
            {"header": "Название", "width": 28},
            {"header": "Ссылка", "width": 28, "link": True},
            {"header": "Кол-во подписчиков", "width": 21, "align": "center", "format": NUM_FMT},
            {"header": "Ниша", "width": 20, "align": "center"},
            {"header": "Комментарии", "width": 30},
            {"header": "Кто зовет", "width": 22, "align": "center"},
        ],
        "sections": ["СМИ", "Блогеры", "Партнеры", "VIP-гости"],
        "min_rows": 12,
    },
    "bloggers": {
        "kind": "table",
        "name": "Список блогеров",
        "title": "Список блогеров",
        "numbered": False,
        "columns": [
            {"header": "Имя", "width": 28, "bold": True},
            {"header": "Ссылка", "width": 30, "link": True},
            {"header": "Кол-во подписчиков", "width": 21, "align": "center", "format": NUM_FMT},
            {"header": "Род деятельности", "width": 30},
            {"header": "Статус", "width": 24, "status": ["Не связались", "Ожидаем ответ", "Подтвердил", "Отказ"]},
        ],
        "sections": ["Telegram", "Instagram"],
        "min_rows": 10,
    },
    "media-list": {
        "kind": "table",
        "name": "Медиалист",
        "title": "Медиалист",
        "numbered": True,
        "columns": [
            {"header": "СМИ / площадка", "width": 34, "bold": True},
            {"header": "Рубрика / формат", "width": 26},
            {"header": "Контакт", "width": 30},
            {"header": "Охват", "width": 16, "align": "center", "format": NUM_FMT},
            {"header": "Статус", "width": 24, "status": ["Не связались", "Отправлен релиз", "Публикация вышла", "Отказ"]},
            {"header": "Ссылка на публикацию", "width": 34, "link": True},
        ],
        "min_rows": 20,
    },
    "roadmap": {
        "kind": "table",
        "name": "Road map",
        "title": "Road map проекта",
        "numbered": False,
        "columns": [
            {"header": "Блок работ", "width": 30, "bold": True},
            {"header": "Описание", "width": 50},
            {"header": "Опорные даты", "width": 22, "align": "center"},
            {"header": "Ответственный", "width": 26, "align": "center"},
            {"header": "Сроки", "width": 22, "align": "center"},
        ],
        "min_rows": 12,
    },
    "publications": {
        "kind": "table",
        "name": "Публикации",
        "title": "Публикации за период",
        "numbered": True,
        "columns": [
            {"header": "Площадка", "width": 30, "bold": True},
            {"header": "Дата", "width": 16, "align": "center", "format": DATE_FMT},
            {"header": "Ссылка", "width": 40, "link": True},
            {"header": "Охват", "width": 18, "align": "center", "format": NUM_FMT},
            {"header": "PR Value, ₽", "width": 18, "align": "center", "format": NUM_FMT},
            {"header": "Комментарий", "width": 30},
        ],
        "total": {"label": "ИТОГО", "sum_columns": ["Охват", "PR Value, ₽"]},
        "min_rows": 20,
    },
    "debrief": {
        "kind": "card",
        "name": "Разбор проекта",
        "fields": [
            "Что прошло хорошо",
            "Какие были проблемы",
            "Что можно улучшить",
            "Количество гостей",
            "Общий охват",
            "Количество публикаций",
        ],
        "tall_rows": True,
    },
}

# ---------------------------------------------------------------------------
# Утилиты стиля
# ---------------------------------------------------------------------------

def side(color: str = BLACK, style: str = "thin") -> Side:
    return Side(style=style, color="FF" + color)


def box(color: str = BLACK, style: str = "thin") -> Border:
    s = side(color, style)
    return Border(left=s, right=s, top=s, bottom=s)


def font(size=SIZE_BODY, bold=False, color=BLACK, underline=None, italic=False) -> Font:
    return Font(name=FONT, size=size, bold=bold, italic=italic, color="FF" + color, underline=underline)


def fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor="FF" + color, bgColor="FF" + color)


def status_colors(value: str):
    v = value.lower()
    if any(w in v for w in GREY_WORDS):
        return STATUS_GREY
    if any(w in v for w in RED_WORDS):
        return STATUS_RED
    if any(w in v for w in GREEN_WORDS):
        return STATUS_GREEN
    if any(w in v for w in YELLOW_WORDS):
        return STATUS_YELLOW
    return STATUS_GREY


def parse_value(v):
    """Строки вида 2026-09-04 / 2026-09-04 19:30 / 19:30 превращаем в даты и время."""
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return dt.datetime.strptime(s, "%Y-%m-%d")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", s):
            return dt.datetime.strptime(s.replace("T", " "), "%Y-%m-%d %H:%M")
        if re.fullmatch(r"\d{1,2}:\d{2}", s):
            h, m = s.split(":")
            return dt.time(int(h), int(m))
    return v


def row_height_for(values, columns) -> float:
    """Высота строки по самой длинной ячейке: ~1.1 символа на единицу ширины колонки, 12.5 pt на строку текста."""
    lines = 1
    if isinstance(values, dict):
        for col in columns:
            v = values.get(col["header"])
            if isinstance(v, str) and col.get("wrap", True):
                width = max(col.get("width", 20), 4)
                for chunk in v.split("\n"):
                    lines = max(lines, -(-len(chunk) // int(width * 1.1)) if chunk else 1)
                lines = max(lines, v.count("\n") + 1)
    return ROW_BODY if lines <= 1 else max(ROW_BODY, 12.5 * lines + 3)


def add_logo(ws, logo_path: Path, cell_row: int, big: bool = False, col_off_px: int = 15, row_off_px: int = 18):
    """Логотип над таблицей: якорь в колонке A, строка cell_row (1-based)."""
    img = XLImage(str(logo_path))
    cx, cy = LOGO_EMU_DASH if big else LOGO_EMU
    img.width = cx / EMU_PER_PX
    img.height = cy / EMU_PER_PX
    marker = AnchorMarker(col=0, colOff=col_off_px * EMU_PER_PX, row=cell_row - 1, rowOff=row_off_px * EMU_PER_PX)
    img.anchor = OneCellAnchor(_from=marker, ext=XDRPositiveSize2D(cx, cy))
    ws.add_image(img)


def page_setup(ws):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5)
    ws.sheet_format.defaultRowHeight = ROW_BODY


# ---------------------------------------------------------------------------
# Лист-таблица
# ---------------------------------------------------------------------------

def build_table_sheet(wb, spec: dict, logo: Path, project: str):
    ws = wb.create_sheet(title=spec["name"][:31])
    page_setup(ws)
    if spec.get("hide_gridlines", False):
        ws.sheet_view.showGridLines = False

    columns = spec["columns"]
    numbered = spec.get("numbered", False)
    first_col = 2                             # B — данные начинаются после узкого поля A
    ws.column_dimensions["A"].width = COL_MARGIN

    # Раскладка колонок: [№] + columns
    col_index = {}
    c = first_col
    if numbered:
        ws.column_dimensions[get_column_letter(c)].width = COL_NUMBER
        num_col = c
        c += 1
    for col in columns:
        ws.column_dimensions[get_column_letter(c)].width = col.get("width", 20)
        col_index[col["header"]] = c
        c += 1
    last_col = c - 1
    ws.column_dimensions[get_column_letter(last_col + 1)].width = COL_MARGIN

    # Строки 1–2: логотип; красная линейка под строкой 2
    ws.row_dimensions[1].height = 10
    ws.row_dimensions[2].height = ROW_LOGO
    add_logo(ws, logo, cell_row=2)
    red_rule = Side(style="medium", color="FF" + RED)
    for cc in range(first_col, last_col + 1):
        ws.cell(row=2, column=cc).border = Border(bottom=red_rule)

    # Строка 3: заголовок листа
    ws.row_dimensions[3].height = ROW_TITLE
    ws.merge_cells(start_row=3, start_column=first_col, end_row=3, end_column=last_col)
    t = ws.cell(row=3, column=first_col, value=spec.get("title") or spec["name"])
    t.font = font(SIZE_TITLE, bold=True)
    t.alignment = Alignment(horizontal="left", vertical="center")

    # Строка 4: шапка
    header_row = 4
    ws.row_dimensions[header_row].height = ROW_HEADER
    hdr_font = font(SIZE_HEADER, bold=True)
    hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if numbered:
        # шапка первой колонки объединяется с колонкой № (как в эталоне)
        ws.merge_cells(start_row=header_row, start_column=num_col, end_row=header_row, end_column=num_col + 1)
        for cc in (num_col, num_col + 1):
            cell = ws.cell(row=header_row, column=cc)
            cell.fill = fill(GREY_HEADER); cell.border = box(); cell.font = hdr_font; cell.alignment = hdr_align
        ws.cell(row=header_row, column=num_col, value=columns[0]["header"])
        rest = columns[1:]
    else:
        rest = columns
    for col in rest:
        cell = ws.cell(row=header_row, column=col_index[col["header"]], value=col["header"])
        cell.fill = fill(GREY_HEADER); cell.border = box(); cell.font = hdr_font; cell.alignment = hdr_align

    # Данные
    rows = spec.get("rows", [])
    sections = spec.get("sections")
    zebra = spec.get("zebra", False)
    min_rows = spec.get("min_rows", 0)
    r = header_row + 1
    data_start = r
    n = 0
    status_ranges: dict[int, tuple[list, int]] = {}

    def write_row(values, r, is_filled: bool, idx: int):
        nonlocal n
        border_color = BLACK if is_filled else GREY_LINE
        row_fill = fill(GREY_ZEBRA) if (zebra and idx % 2 == 1) else None
        ws.row_dimensions[r].height = row_height_for(values, columns)
        if numbered:
            cell = ws.cell(row=r, column=num_col, value=idx + 1)
            cell.font = font(SIZE_BODY, bold=True); cell.border = box(border_color)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if row_fill: cell.fill = row_fill
        for col in columns:
            cc = col_index[col["header"]]
            raw = values.get(col["header"]) if isinstance(values, dict) else None
            val = parse_value(raw)
            cell = ws.cell(row=r, column=cc, value=val)
            cell.font = font(SIZE_BODY, bold=col.get("bold", False))
            cell.border = box(border_color)
            cell.alignment = Alignment(horizontal=col.get("align", "left"), vertical="center", wrap_text=col.get("wrap", True))
            if row_fill: cell.fill = row_fill
            if col.get("format") and (isinstance(val, (int, float, dt.date, dt.time, dt.datetime)) or val is None):
                cell.number_format = col["format"]
            if col.get("link") and isinstance(val, str) and val.startswith("http"):
                cell.hyperlink = val
                cell.font = font(SIZE_BODY, color=LINK_BLUE, underline="single")
            if col.get("status"):
                status_ranges.setdefault(cc, (col["status"], r))

    def write_section(label, r):
        ws.row_dimensions[r].height = ROW_BODY
        c0 = num_col if numbered else first_col
        ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=last_col)
        for cc in range(c0, last_col + 1):
            ws.cell(row=r, column=cc).border = box()
        cell = ws.cell(row=r, column=c0, value=label)
        cell.font = font(SIZE_BODY, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        # тонкая красная подчёркивающая линия под заголовком секции
        for cc in range(c0, last_col + 1):
            b = ws.cell(row=r, column=cc).border
            ws.cell(row=r, column=cc).border = Border(left=b.left, right=b.right, top=b.top, bottom=Side(style="medium", color="FF" + RED))

    if sections:
        # Секции: rows могут быть словарём {секция: [строки]} или списком с полем "section"
        grouped: dict[str, list] = {s: [] for s in sections}
        if isinstance(rows, dict):
            for k, v in rows.items():
                grouped.setdefault(k, []).extend(v)
        else:
            for row in rows:
                grouped.setdefault(row.get("section", sections[0]), []).append(row)
        per_section = max(3, min_rows // max(1, len(grouped)))
        for label, items in grouped.items():
            write_section(label, r); r += 1
            i = 0
            for item in items:
                write_row(item, r, True, i); r += 1; i += 1
            while i < per_section:
                write_row({}, r, False, i); r += 1; i += 1
    else:
        i = 0
        for item in rows:
            write_row(item, r, True, i); r += 1; i += 1
        while i < min_rows:
            write_row({}, r, False, i); r += 1; i += 1
    data_end = r - 1

    # Итоговая строка
    total = spec.get("total")
    if total:
        r += 1
        ws.row_dimensions[r].height = ROW_BODY
        c0 = num_col if numbered else first_col
        label_end = c0 + 1 if not numbered and len(columns) > 1 else c0
        ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=label_end)
        for cc in range(c0, last_col + 1):
            cell = ws.cell(row=r, column=cc); cell.fill = fill(GREY_TOTAL); cell.border = box(); cell.font = font(SIZE_BODY, bold=True)
        ws.cell(row=r, column=c0, value=total.get("label", "ИТОГО"))
        for h in total.get("sum_columns", []):
            cc = col_index.get(h)
            if not cc: continue
            L = get_column_letter(cc)
            cell = ws.cell(row=r, column=cc, value=f"=SUM({L}{data_start}:{L}{data_end})")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.number_format = next((c.get("format", NUM_FMT) for c in columns if c["header"] == h), NUM_FMT)

    # Статусы: выпадающий список + подсветка
    for cc, (values, start_r) in status_ranges.items():
        L = get_column_letter(cc)
        rng = f"{L}{start_r}:{L}{data_end}"
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True, showErrorMessage=True)
        ws.add_data_validation(dv); dv.add(rng)
        for v in values:
            bg, fg = status_colors(v)
            ws.conditional_formatting.add(
                rng,
                FormulaRule(formula=[f'${L}{start_r}="{v}"'], fill=fill(bg), font=Font(name=FONT, size=SIZE_BODY, color="FF" + fg), stopIfTrue=True),
            )

    if spec.get("freeze", False):
        ws.freeze_panes = ws.cell(row=header_row + 1, column=first_col)
    if spec.get("autofilter", False):
        ws.auto_filter.ref = f"{get_column_letter(num_col if numbered else first_col)}{header_row}:{get_column_letter(last_col)}{data_end}"
    return ws


# ---------------------------------------------------------------------------
# Лист-карточка (дашборд, разбор проекта)
# ---------------------------------------------------------------------------

def build_card_sheet(wb, spec: dict, logo: Path, project: str):
    ws = wb.create_sheet(title=spec["name"][:31])
    page_setup(ws)
    ws.column_dimensions["A"].width = 1.71
    ws.column_dimensions["B"].width = spec.get("label_width", 32)
    ws.column_dimensions["C"].width = spec.get("value_width", 68)
    ws.column_dimensions["D"].width = 8

    ws.row_dimensions[1].height = 52.5
    add_logo(ws, logo, cell_row=1, big=True, col_off_px=12, row_off_px=2)
    ws.merge_cells("B1:C1")

    # Название проекта в красной рамке
    ws.row_dimensions[2].height = spec.get("title_height", 105 if spec.get("kind_title_big", True) else 52.5)
    ws.merge_cells("B2:C2")
    tcell = ws["B2"]
    tcell.value = spec.get("title") or project
    tcell.font = font(SIZE_DASH_TITLE, bold=True)
    tcell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
    thick = Side(style="thick", color="FF" + RED)
    ws["B2"].border = Border(left=thick, top=thick, bottom=thick)
    ws["C2"].border = Border(right=thick, top=thick, bottom=thick)
    ws.row_dimensions[3].height = 18.75

    values = spec.get("values", {})
    r = 4
    tall = spec.get("tall_rows", False)
    for label in spec.get("fields", []):
        ws.row_dimensions[r].height = 60 if tall else ROW_BODY + 3
        lc = ws.cell(row=r, column=2, value=label)
        lc.font = font(SIZE_BODY, bold=True); lc.border = box(DARK_GREY)
        lc.alignment = Alignment(horizontal="left", vertical="top" if tall else "center", wrap_text=True)
        raw = values.get(label)
        val = parse_value(raw)
        vc = ws.cell(row=r, column=3, value=val)
        vc.font = font(SIZE_BODY); vc.border = box(DARK_GREY)
        vc.alignment = Alignment(horizontal="left", vertical="top" if tall else "center", wrap_text=True)
        if isinstance(val, dt.datetime):
            vc.number_format = DATE_LONG_FMT
        if isinstance(val, str) and val.startswith("http"):
            vc.hyperlink = val; vc.font = font(SIZE_BODY, color=LINK_BLUE, underline="single")
        r += 1
    return ws


# ---------------------------------------------------------------------------
# Сборка книги
# ---------------------------------------------------------------------------

def resolve_sheet(spec: dict) -> dict:
    """Пресет + переопределения пользователя → полная спецификация листа."""
    preset_name = spec.get("preset")
    base = copy.deepcopy(PRESETS[preset_name]) if preset_name else {"kind": spec.get("kind", "table")}
    if preset_name and preset_name not in PRESETS:
        raise SystemExit(f"Неизвестный пресет: {preset_name}. Доступны: {', '.join(PRESETS)}")
    merged = {**base, **{k: v for k, v in spec.items() if k != "preset"}}
    # добавочные колонки, не заменяющие пресетные
    if "extra_columns" in spec:
        merged["columns"] = merged.get("columns", []) + spec["extra_columns"]
    if merged.get("kind") == "table" and "columns" not in merged:
        raise SystemExit(f"Лист «{merged.get('name')}»: нужны columns или preset")
    return merged


def build_workbook(spec: dict, out: Path, logo: Path | None = None) -> Path:
    logo = Path(logo or spec.get("logo") or DEFAULT_LOGO)
    if not logo.exists():
        raise SystemExit(f"Логотип не найден: {logo}")
    project = spec.get("project", "GORD AGENCY x BRAND")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet in spec["sheets"]:
        s = resolve_sheet(sheet)
        if s["kind"] == "card":
            build_card_sheet(wb, s, logo, project)
        else:
            build_table_sheet(wb, s, logo, project)
    wb.properties.creator = "GORD Agency"
    wb.properties.title = project
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def example_spec(name: str) -> dict:
    path = HERE / "examples" / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"Нет примера {name}. Есть: {', '.join(p.stem for p in (HERE / 'examples').glob('*.json'))}")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", help="JSON-спецификация книги")
    ap.add_argument("out", nargs="?", help="путь к результату .xlsx")
    ap.add_argument("--example", help="собрать встроенный пример (event-project, monthly-report, simple-plan)")
    ap.add_argument("--logo", help="свой PNG-логотип вместо стандартного")
    ap.add_argument("--presets", action="store_true", help="показать пресеты листов и выйти")
    a = ap.parse_args(argv)

    if a.presets:
        for k, v in PRESETS.items():
            cols = ", ".join(c["header"] for c in v.get("columns", [])) if v["kind"] == "table" else ", ".join(v["fields"])
            print(f"{k:16} [{v['kind']}] «{v['name']}»: {cols}")
        return
    if a.example:
        spec = example_spec(a.example)
        out = Path(a.spec or a.out or f"{a.example}.xlsx")
    else:
        if not a.spec or not a.out:
            ap.error("укажи spec.json и out.xlsx (или --example NAME out.xlsx)")
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        out = Path(a.out)
    build_workbook(spec, out, a.logo)
    print(f"OK → {out}  ({len(spec['sheets'])} лист(ов))")


if __name__ == "__main__":
    main()
