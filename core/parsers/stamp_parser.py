"""Разбор штампа документа из нижнего колонтитула DOCX (Этап 1.4).

Штамп — таблица в колонтитуле по ГОСТ 21.1101. Разметка берётся из
описания штампа (`stamp description.xlsx`): сетка из 10 столбцов и 11
строк, где **столбцы нумеруются слева направо, а строки — снизу вверх**.

    строка 11        +----------+------------------------+
    строка 9         |          | Наименование титула    |
    строка 8         | Изм.|Кол.уч|Лист|№док|Подп.|Дата  |
    строка 7         | подписи граф изменений             |
    строки 1..6      | исполнители     | Стадия|Лист|Листов
    столбцы          1..6            | 7 | 8 | 9 | 10

Ключевые координаты (строка, столбец):

    8,1  Изм.      8,3  статус листа (Нов./Зам.)   8,6  дата изменения
    5,8  Стадия    5,9  Лист                       5,10 Листов
    10,7            шифр документа

Таблица в DOCX разворачивается по `gridSpan` в полную сетку из 10
столбцов и по `vMerge` — вниз, поэтому значения объединённых ячеек
доступны в каждой строке объединения.
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from typing import Any

from lxml import etree

from core.doc_types import UNKNOWN as UNKNOWN_DOC_TYPE
from core.doc_types import doc_type_from_name, normalize_doc_type

# Коды реквизитов штампа (они же ключи в stamp_raw["values"]).
LABEL_DOC_CODE = "шифр"
LABEL_REVISION = "изм"
LABEL_COUNT = "колуч"
LABEL_UPDATE_STATUS = "статуслиста"
LABEL_DOC_NUMBER = "№док"
LABEL_SIGNATURE = "подп"
LABEL_DATE = "дата"
LABEL_STAGE = "стадия"
LABEL_SHEET = "лист"
LABEL_SHEETS = "листов"
LABEL_TITLE = "наименование"
LABEL_ORGANIZATION = "организация"
LABEL_OBJECT = "объект"
LABEL_DOCUMENT = "документ"
LABEL_PROFILE = "профиль"

# Раскладки штампа (см. `detect_stamp_profile`).
STAMP_PROFILE_FULL = "full"
STAMP_PROFILE_SHORT = "short"
STAMP_PROFILE_UNKNOWN = "unknown"

# Титул, слитый с названием документа: «I этап строительства Наружное …».
STAGE_TITLE_RE = re.compile(r"^([IVX]+\s+этап\s+строительства\.?)\s*(.*)$", re.IGNORECASE)

# Координаты реквизитов: (строка, столбец) по нумерации описания штампа —
# строки снизу вверх, столбцы слева направо.
STAMP_CELLS: dict[str, tuple[int, int]] = {
    LABEL_DOC_CODE: (10, 7),
    LABEL_TITLE: (9, 7),
    LABEL_ORGANIZATION: (3, 8),
    LABEL_REVISION: (8, 1),
    LABEL_COUNT: (8, 2),
    LABEL_UPDATE_STATUS: (8, 3),
    LABEL_DOC_NUMBER: (8, 4),
    LABEL_SIGNATURE: (8, 5),
    LABEL_DATE: (8, 6),
    LABEL_STAGE: (5, 8),
    LABEL_SHEET: (5, 9),
    LABEL_SHEETS: (5, 10),
}

# Сетка штампа по описанию: 11 строк снизу вверх, 10 столбцов слева направо
# (см. `stamp description.xlsx`). Координаты — записи `STAMP_CELLS`.

# Подписи строки граф изменений штампа (строка 7 сетки, столбцы 1..6).
# Они же служат опорой: число строк запаса в реальной таблице меняется,
# поэтому положение строки определяется по этим подписям.
CHANGE_LABELS = (
    "Изм.",
    "Кол.уч",
    "Лист",
    "№док",
    "Подп.",
    "Подпись",
    "Дата",
    "Стадия",
    "Листов",
)

# Номер строки сетки, на которой стоят подписи `CHANGE_LABELS`
# (см. `stamp description.xlsx`). От неё ведётся отсчёт координат
# в реальных таблицах (см. `anchored_cell`).
CHANGE_LABEL_ROW = 8

# Столбцы сетки с 1-го по этот сдвигаются вместе, если подпись `Лист`
# объединена на два столбца (см. `_column_shift`). Правее начинается блок
# `Стадия | Лист | Листов` и шифра, он в бланках не сдвигается.
_SHIFTABLE_COLUMNS = 6

# Смещение вверх от строки подписей до строки с нужным значением, в
# номерах строк сетки описания. В описании значения лежат ниже подписей
# (строка 8 -> 9 -> 10), но в реальных колонтитулах они стоят выше:
# `Лист | Листов` на строке 6, исполнители на строке 6-7, шифр на 10-11.
# Для ячеек, которых нет в `SHIFT`, смещение считается по описанию.
SHIFT: dict[int, int] = {
    5: 2,
    6: 2,
    7: 1,
    8: 0,
    9: -1,
    10: -2,
    11: -3,
}

# Шифр: группы из заглавных букв/цифр через дефис, тип — после точки.
DOC_CODE_RE = re.compile(r"^[А-ЯЁA-Z][А-ЯЁA-Z0-9]*(?:-[А-ЯЁA-Z0-9]+)*\.[А-ЯЁA-Z][А-ЯЁA-Z0-9]*$")
DOC_TYPE_RE = re.compile(r"\.[А-ЯЁA-Z][А-ЯЁA-Z0-9]*$")
# Шифр без типа документа после точки: `ЕСТ-ПМ-80825-Р-1-АСДУ`.
DOC_CODE_BARE_RE = re.compile(r"^[А-ЯЁA-Z][А-ЯЁA-Z0-9]*(?:-[А-ЯЁA-Z0-9]+){3,}$")
HYPHEN_SPACES_RE = re.compile(r"\s*-\s*")
DATE_RE = re.compile(r"^([0-9]{1,2})[.\-/]([0-9]{1,2})[.\-/]([0-9]{2}|[0-9]{4})$")
FILENAME_DATE_RE = re.compile(
    r"(?:^|[^0-9])([0-9]{1,2})[.\-_]([0-9]{1,2})[.\-_]([0-9]{2,4})(?:[^0-9]|$)"
)
SPACES_RE = re.compile(r"\s+")
FIRST_DIGIT_RE = re.compile(r"^[0-9]")

STAMP_OK = "OK"
STAMP_PARTIAL = "PARTIAL"
STAMP_MISSING = "MISSING"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"


def clean_text(value: Any) -> str:
    """Склеивает содержимое ячейки в строку без служебных меток картинок."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [clean_text(item) for item in value]
        text = " ".join(part for part in parts if part)
    else:
        text = str(value)
    text = text.replace("\u00a0", " ")
    text = SPACES_RE.sub(" ", text)
    return text.strip()


def parse_revision_date(text: str) -> str | None:
    """Приводит дату штампа (`01.08.25`) к ISO (`2025-08-01`)."""
    if not text:
        return None
    match = DATE_RE.match(text.strip())
    if not match:
        return None
    day, month, year = match.groups()
    if len(year) == 2:
        year = "20" + year
    return year + "-" + month.zfill(2) + "-" + day.zfill(2)


def parse_date_from_filename(filename: str) -> str | None:
    """Дата выпуска из имени файла для неофициальных документов."""
    base = os.path.basename(filename)
    for match in FILENAME_DATE_RE.finditer(base):
        day, month, year = match.groups()
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            continue
        if len(year) == 2:
            year = "20" + year
        return year + "-" + month.zfill(2) + "-" + day.zfill(2)
    return None


def fallback_revision_date(file_path: str) -> tuple[str | None, str]:
    """Дата, если в штампе её нет: сначала из имени файла, затем дата
    последнего изменения файла. Возвращает (ISO-дата, источник), источник —
    `filename`, `modified` или пустая строка."""
    from_name = parse_date_from_filename(file_path)
    if from_name:
        return from_name, "filename"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(file_path))), "modified"
    except OSError:
        return None, ""


_NAME_YMD_RE = re.compile(r"(?<![0-9])(20[0-9]{2})[.\-_]([0-9]{1,2})[.\-_]([0-9]{1,2})(?![0-9])")
_NAME_DMY_RE = re.compile(r"(?<![0-9])([0-9]{1,2})[.\-_]([0-9]{1,2})[.\-_]([0-9]{4}|[0-9]{2})(?![0-9])")
_NAME_YM_RE = re.compile(r"(?<![0-9])(20[0-9]{2})[.\-_]([0-9]{1,2})(?![0-9])")
_NAME_REVISION_RE = re.compile(r"изм\.?\s*([0-9]{1,2})(?![0-9])(?![.\-][0-9])", re.IGNORECASE)


def find_dates_in_filename(filename: str) -> list[str]:
    """Все даты из имени файла: `YYYY-MM-DD` или `YYYY-MM` (если дня нет).

    Понимает `2025.08.15`, `2026-09-17`, `17.06.26`, `1.02.2023` и
    `2026.04`. Список отсортирован по возрастанию.
    """
    text = os.path.basename(filename)
    found: list[str] = []

    def blank(match: Any) -> str:
        return " " * len(match.group(0))

    def valid(day: int, month: int) -> bool:
        return 1 <= month <= 12 and 1 <= day <= 31

    for match in _NAME_YMD_RE.finditer(text):
        year, month, day = match.groups()
        if valid(int(day), int(month)):
            found.append(year + "-" + month.zfill(2) + "-" + day.zfill(2))
    text = _NAME_YMD_RE.sub(blank, text)
    for match in _NAME_DMY_RE.finditer(text):
        day, month, year = match.groups()
        if valid(int(day), int(month)):
            if len(year) == 2:
                year = "20" + year
            found.append(year + "-" + month.zfill(2) + "-" + day.zfill(2))
    text = _NAME_DMY_RE.sub(blank, text)
    for match in _NAME_YM_RE.finditer(text):
        year, month = match.groups()
        if 1 <= int(month) <= 12:
            found.append(year + "-" + month.zfill(2))
    return sorted(set(found))


def newest_filename_date(filename: str) -> str | None:
    """Самая поздняя дата из имени файла в виде `YYYY-MM-DD`.

    Дата без дня (`2026.04`) считается первым числом месяца.
    """
    dates = [d if len(d) == 10 else d + "-01" for d in find_dates_in_filename(filename)]
    return max(dates) if dates else None


def find_revision_in_filename(filename: str) -> str:
    """Номер изменения из имени файла (`Изм.2` -> `2`), `""` если не указан."""
    matches = _NAME_REVISION_RE.findall(os.path.basename(filename))
    if not matches:
        return ""
    return matches[-1].lstrip("0") or "0"


def compare_with_filename(filename: str, revision: str, revision_date: str | None) -> list[dict[str, str]]:
    """Расхождения между штампом и именем файла для решения пользователя.

    Парсер ничего не исправляет: каждое расхождение попадает в результат
    как запись `field`, `stamp`, `filename`, `message`.
    """
    issues: list[dict[str, str]] = []
    name_dates = find_dates_in_filename(filename)
    if name_dates and revision_date:
        latest = name_dates[-1]
        if not revision_date.startswith(latest):
            issues.append(
                {
                    "field": "revision_date",
                    "stamp": revision_date,
                    "filename": latest,
                    "message": "дата в штампе " + revision_date + " не совпадает с датой в имени файла " + latest,
                }
            )
    name_revision = find_revision_in_filename(filename)
    if name_revision and revision and name_revision != (revision.lstrip("0") or "0"):
        issues.append(
            {
                "field": "revision",
                "stamp": revision,
                "filename": name_revision,
                "message": "изменение в штампе " + revision + " не совпадает с изменением в имени файла " + name_revision,
            }
        )
    return issues


def normalize_doc_code(text: str) -> str:
    """Шифр в верхнем регистре, без пробелов вокруг дефисов и перед точкой.

    В части штампов набрано `Р-1- АСТУЭ.КЖ`: пробел после дефиса.
    """
    cleaned = HYPHEN_SPACES_RE.sub("-", clean_text(text).upper())
    return re.sub(r"\s+\.", ".", cleaned)


DEFAULT_DOC_TYPE = "XN"  # тип для шифров, где тип документа не указан


def is_bare_doc_code(text: str) -> bool:
    """Шифр без типа документа (`…-АСДУ`): не меньше четырёх групп через дефис."""
    cleaned = normalize_doc_code(text)
    return bool(DOC_CODE_BARE_RE.match(cleaned)) and bool(re.findall(r"[0-9]", cleaned))


def is_doc_code(text: str) -> bool:
    """Похоже ли значение на шифр документа (дефисы, цифры, без пробелов)."""
    cleaned = normalize_doc_code(text)
    if not cleaned or not DOC_CODE_RE.match(cleaned):
        return False
    if "-" not in cleaned:
        return False
    if not re.findall(r"[0-9]", cleaned):
        return False
    return len(cleaned) >= 6


def looks_like_doc_code(text: str) -> bool:
    """Похоже ли значение на шифр документа: дефисы, цифры и тип.

    Мягче `is_doc_code` (не требует длины), но тоже требует структуру
    `XXX-NNN-...` с типом документа после точки.
    """
    cleaned = normalize_doc_code(text)
    if not cleaned or not DOC_CODE_RE.match(cleaned):
        return False
    if "-" not in cleaned:
        return False
    return bool(re.findall(r"[0-9]", cleaned))


def parse_doc_code(doc_code: str) -> dict[str, str]:
    """Разбирает шифр документа на проект, раздел и тип.

    `ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР` -> проект `ЕСТ-ПМ`, раздел `80825-Р-1-ИСВН`,
    тип `ВОР`. Граница проекта — первая группа после дефиса, начинающаяся
    с цифры (номер проекта).
    """
    code = clean_text(doc_code).upper()
    if not code:
        return {"doc_code": "", "project_code": "", "section_code": "", "doc_type": ""}

    type_match = DOC_TYPE_RE.search(code)
    if type_match:
        doc_type = type_match.group(0)[1:]
        base = code[: type_match.start()]
    else:
        doc_type = ""
        base = code

    parts = [part for part in base.split("-") if part]
    # Граница проекта — последний `-N`, где N — номер комплекта (только
    # цифры). Всё до него — проект, всё после — раздел.
    split_at = -1
    for index in range(1, len(parts) - 1):
        if parts[index].isdigit():
            split_at = index
    if split_at < 0:
        project_code = "-".join(parts)
        section_code = ""
    else:
        project_code = "-".join(parts[:split_at])
        section_code = "-".join(parts[split_at + 1 :])

    return {
        "doc_code": code,
        "project_code": project_code,
        "section_code": section_code,
        "doc_type": doc_type,
    }


def _cell_text(tc: Any) -> str:
    """Текст ячейки таблицы Word: абзацы объединяются через пробел."""
    paragraphs: list[str] = []
    for paragraph in tc.iter(W + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(W + "t"))
        text = clean_text(text)
        if text:
            paragraphs.append(text)
    return " ".join(paragraphs)


def _grid_span(tc: Any) -> int:
    """Сколько столбцов покрывает ячейка (`w:gridSpan`)."""
    tc_pr = tc.find(W + "tcPr")
    if tc_pr is None:
        return 1
    span = tc_pr.find(W + "gridSpan")
    if span is None:
        return 1
    try:
        value = int(span.get(W + "val") or "1")
    except ValueError:
        return 1
    return value if value > 0 else 1


def _vertical_merge(tc: Any) -> str:
    """Режим вертикального объединения: `restart`, `continue` или пусто."""
    tc_pr = tc.find(W + "tcPr")
    if tc_pr is None:
        return ""
    merge = tc_pr.find(W + "vMerge")
    if merge is None:
        return ""
    return merge.get(W + "val") or "continue"


def _table_width(tbl: Any) -> int:
    """Ширина сетки таблицы по `w:tblGrid` (0, если сетка не описана)."""
    grid = tbl.find(W + "tblGrid")
    if grid is None:
        return 0
    return len(grid.findall(W + "gridCol"))


def read_table_rows(tbl: Any) -> list[list[str]]:
    """Разворачивает таблицу Word в прямоугольную сетку значений.

    Столбцы восстанавливаются по `w:gridSpan`, вертикальные объединения
    (`w:vMerge`) раскрываются вниз. Значение ячейки берётся из самого
    документа; объединение только переносит его, если в строке оно пусто.
    Ширина сетки берётся из `w:tblGrid`, иначе — по самой широкой строке:
    пустые ячейки строки тоже являются столбцами сетки.
    """
    rows: list[list[str]] = []
    for tr in tbl.findall(W + "tr"):
        row: list[str] = []
        for tc in tr.findall(W + "tc"):
            text = _cell_text(tc)
            merge = _vertical_merge(tc)
            span = _grid_span(tc)
            if merge == "continue" and not text and rows:
                position = len(row)
                previous = rows[len(rows) - 1]
                if position < len(previous):
                    text = previous[position]
            for _ in range(span):
                row.append(text)
        rows.append(row)

    width = _table_width(tbl)
    for row in rows:
        if len(row) > width:
            width = len(row)
    for row in rows:
        while len(row) < width:
            row.append("")
    return rows


def find_change_label_row(rows: list[list[str]]) -> int:
    """Индекс строки с подписями граф изменений (`-1`, если строки нет).

    Подписи ищутся по всем столбцам: в объединённом правом блоке они
    тоже встречаются. Строка шифра подписями не считается — в ней шифр
    дублируется в нескольких графах.
    """
    for index in range(len(rows)):
        row = rows[index]
        hits = 0
        for label in CHANGE_LABELS:
            bare = label.rstrip(".")
            for text in row:
                value = clean_text(text)
                if value == label or value == bare:
                    hits += 1
                    break
        if hits >= 4:
            return index
    return -1


def cell_of(rows: list[list[str]], row_number: int, column_number: int) -> str:
    """Значение ячейки по координатам описания штампа.

    `row_number` считается снизу вверх (1 — нижняя строка), `column_number`
    — слева направо (1 — левый столбец). Если строк в таблице меньше, чем
    в сетке, отсутствующие строки сверху считаются пустыми.
    """
    if not rows:
        return ""
    index = len(rows) - row_number
    if index < 0:
        return ""
    if index >= len(rows):
        return ""
    row = rows[index]
    position = column_number - 1
    if position < 0 or position >= len(row):
        return ""
    return clean_text(row[position])


def is_change_label(text: str) -> bool:
    """Является ли текст подписью граф изменений (`Изм.`, `№ док.` и т. п.)."""
    value = clean_text(text)
    if not value:
        return False
    compact = value.replace(".", "").replace(" ", "").lower()
    for label in CHANGE_LABELS:
        bare = label.replace(".", "").replace(" ", "").lower()
        if compact == bare:
            return True
    return False


def _main_shift(row_number: int) -> int:
    """Основное смещение вверх от подписей для строки сетки."""
    return SHIFT.get(row_number, CHANGE_LABEL_ROW - row_number)


def _shift_candidates(row_number: int) -> tuple[int, ...]:
    """Смещения (вверх от подписей), которые стоит проверить для строки.

    Соседние строки просматриваются только для `Стадия`/`Лист`/`Листов`:
    в одних бланках они делят строку с подписями, в других стоят выше.
    Для остальных граф берётся исключительно основное смещение `SHIFT`:
    соседняя строка там — это исполнители (`Разработал`, `Проверил`),
    и брать её за значение нельзя.
    """
    main = _main_shift(row_number)
    if row_number in (LABEL_STAGE, LABEL_SHEET, LABEL_SHEETS):
        return (main, main + 1, main + 2, main - 1)
    if row_number == CHANGE_LABEL_ROW:
        # Значения граф изменений всегда выше подписей; `main` = 0 — это
        # сама строка подписей, начинать с неё нельзя.
        return (1,)
    return (main,)


def grid_cell(rows: list[list[str]], row_number: int, column_number: int) -> str:
    """Значение по координатам сетки описания — без подгонки под бланк.

    Считается снизу вверх от последней строки таблицы. В разных бланках
    относительно этой сетки значения сдвинуты, поэтому результат годится
    только как кандидат: он проверяется на правдоподобие рядом функций.
    """
    return cell_of(rows, row_number, column_number)


def _row_value(rows: list[list[str]], index: int, column_number: int) -> str:
    """Текст ячейки по индексу строки таблицы и номеру столбца сетки."""
    if index < 0 or index >= len(rows):
        return ""
    row = rows[index]
    position = column_number - 1
    if position < 0 or position >= len(row):
        return ""
    return clean_text(row[position])


def read_sheet_values(rows: list[list[str]]) -> tuple[str, str]:
    """Значения граф `Лист` и `Листов` (столбцы 9 и 10 сетки штампа).

    Строки подписей в бланках стоят по-разному, поэтому значение ищется
    сначала в строке подписей (`Стадия | Лист | Листов` делят с ними одну
    строку), затем над подписями и ниже — по одному шагу.
    """
    anchor = find_change_label_row(rows)
    shift = _column_shift(rows)
    sheet_column = 9 + (shift if 9 <= _SHIFTABLE_COLUMNS else 0)
    total_column = 10 + (shift if 10 <= _SHIFTABLE_COLUMNS else 0)
    if anchor < 0:
        return (
            _plausible_sheet(cell_of(rows, 5, sheet_column)),
            _plausible_sheet(cell_of(rows, 5, total_column)),
        )
    for offset in (0, 1, 2, 3):
        sheet = _plausible_sheet(_row_value(rows, anchor - offset, sheet_column))
        total = _plausible_sheet(_row_value(rows, anchor - offset, total_column))
        if sheet and total:
            return sheet, total
    for offset in (0, 1, 2, 3):
        sheet = _plausible_sheet(_row_value(rows, anchor + offset, sheet_column))
        total = _plausible_sheet(_row_value(rows, anchor + offset, total_column))
        if sheet and total:
            return sheet, total
    return "", ""


def _plausible_sheet(text: str) -> str:
    """Похоже ли значение на `Лист`/`Листов` (`1`, `1.1`), а не на текст."""
    value = clean_text(text)
    if not value or is_change_label(value):
        return ""
    if len(value) > 8:
        return ""
    if not re.match(r"^[0-9]", value):
        return ""
    return value


def anchored_cell(
    rows: list[list[str]],
    row_number: int,
    column_number: int,
    search: bool = True,
) -> str:
    """Значение ячейки штампа с отсчётом от строки подписей.

    В колонтитулах значения стоят над строкой подписей
    (`Изм. | Кол.уч | Лист | №док | Подп. | Дата`), а не под ней: `Лист` и
    `Листов` — двумя строками выше, исполнители и `Дата` — одной. Число
    строк запаса меняется от документа к документу, поэтому отсчёт ведётся
    от подписей. Если заданная по описанию ячейка уже заполнена, она
    возвращается как есть: таблица может быть построена точно по сетке.
    Дальше берётся ячейка по `SHIFT`, а при `search` — ещё и соседние
    строки: подписи в бланках стоят на разной высоте, и значение графы
    изменений иногда оказывается на строку выше или ниже.

    Подписи самих граф (`Стадия`, `Лист`, `Изм.`) значением не считаются,
    как и должности исполнителей (`Разработал`, `Проверил`, `ГИП`).
    """
    anchor = find_change_label_row(rows)
    if anchor < 0:
        return cell_of(rows, row_number, column_number)

    for index in _row_candidates(rows, row_number, anchor):
        value = _row_value(rows, index, column_number)
        if value and not is_change_label(value):
            return value
    return ""


def _row_candidates(rows: list[list[str]], row_number: int, anchor: int) -> tuple[int, ...]:
    """Строки, где может лежать значение: от подписей и от низа таблицы.

    В разных бланках одна и та же графа стоит либо над подписями (сдвиг
    `SHIFT`), либо на своём месте в сетке, отсчитанной от последней строки
    таблицы (`cell_of`). Проверяются оба варианта; сетка идёт первой, она
    точна для таблиц, построенных по описанию.
    """
    candidates: list[int] = []
    grid_index = len(rows) - row_number
    if 0 <= grid_index < len(rows):
        candidates.append(grid_index)
    for offset in _shift_candidates(row_number):
        index = anchor - offset
        if 0 <= index < len(rows) and index not in candidates:
            candidates.append(index)
    return tuple(candidates)


def _is_value(text: str) -> bool:
    """Годится ли текст ячейки как значение реквизита, а не как подпись."""
    return bool(text) and not is_change_label(text) and text not in ROLE_LABELS


def change_label_of(rows: list[list[str]], column_number: int) -> str:
    """Подпись графы в заданном столбце строки подписей.

    В бланках, где подписи объединены (`Лист` на два столбца), эта подпись
    стоит и в столбце значений. По ней видно, что колонка «съехала» и
    значение нужно искать в соседней.
    """
    anchor = find_change_label_row(rows)
    if anchor < 0 or column_number < 1:
        return ""
    return _row_value(rows, anchor, column_number)


ROLE_LABELS = ("Разработал", "Проверил", "ГИП", "Н.контр.", "Утв.")



def _has_change_labels(rows: list[list[str]]) -> bool:
    """Есть ли в таблице строка граф изменений (`Изм. | Кол.уч | ...`)."""
    return find_change_label_row(rows) >= 0


def find_doc_code(rows: list[list[str]]) -> str:
    """Шифр документа из таблицы штампа.

    Сначала берётся ячейка по координатам описания, затем — любая ячейка
    правого блока (`tblGrid` короче сетки штампа), затем — любая ячейка
    таблицы: шифр продублирован в нескольких графах.
    """
    row_number, column_number = STAMP_CELLS[LABEL_DOC_CODE]
    text = anchored_cell(rows, row_number, column_number)
    if looks_like_doc_code(text):
        return normalize_doc_code(text)

    for row in rows:
        for value in row:
            if looks_like_doc_code(value):
                return normalize_doc_code(value)

    # Шифр без типа документа (`…-АСДУ`): только как запасной вариант.
    if is_bare_doc_code(text):
        return normalize_doc_code(text)
    for row in rows:
        for value in row:
            if is_bare_doc_code(value):
                return normalize_doc_code(value)
    return ""


def is_stamp_table(rows: list[list[str]]) -> bool:
    """Похожа ли таблица на штамп: строка граф изменений и шифр документа."""
    if not rows:
        return False
    if not _has_change_labels(rows):
        return False
    return bool(find_doc_code(rows))


def _footer_part_names(archive: zipfile.ZipFile) -> list[str]:
    """Части пакета с колонтитулами (`word/footer*.xml`)."""
    names: list[str] = []
    for name in archive.namelist():
        if not name.startswith("word/footer"):
            continue
        if not name.endswith(".xml"):
            continue
        names.append(name)
    names.sort()
    return names


def read_stamp_tables(file_path: str) -> list[list[list[str]]]:
    """Все таблицы колонтитулов документа, похожие на штамп."""
    tables: list[list[list[str]]] = []
    with zipfile.ZipFile(file_path) as archive:
        for name in _footer_part_names(archive):
            try:
                root = etree.fromstring(archive.read(name))
            except Exception:  # noqa: BLE001
                continue
            for tbl in root.iter(W + "tbl"):
                rows = read_table_rows(tbl)
                if is_stamp_table(rows):
                    tables.append(rows)
    return tables


def _digits(text: str) -> str:
    return "".join(re.findall(r"[0-9]", text))


def _to_int(text: str) -> int | None:
    """Первое число из строки (`035` -> 35, `1.9` -> 1)."""
    digits = _digits(text)
    if not digits:
        return None
    return int(digits)


def _sheet_numbers(text: str) -> tuple[int | None, int | None]:
    """Возвращает (лист, часть листа) из значения вида `1` или `1.1`."""
    parts = [part for part in re.split(r"[.\-/]", text) if part]
    if not parts:
        return None, None
    first = _to_int(parts[0])
    second = _to_int(parts[1]) if len(parts) > 1 else None
    return first, second


def _revision_value(value: str) -> str:
    """Номер изменения из штампа: `1` -> `1`, `Зам.`/`Нов.` -> `0`."""
    text = value.strip()
    lowered = text.lower()
    if lowered.startswith("нов"):
        return "0"
    if lowered.startswith("зам"):
        return "0"
    digits = _digits(text)
    if digits:
        return digits
    return text


_CHANGE_NUMBER_RE = re.compile(r"^[0-9]{1,2}$")
# Сколько строк вверх от подписей просматривается в поисках граф изменений.
_MAX_CHANGE_ROWS = 12


def latest_change_row(rows: list[list[str]]) -> int:
    """Индекс строки последнего изменения в штампе (`-1`, если граф нет).

    Графы изменений стоят над строкой подписей `Изм. | Кол.уч | ...`: первое
    изменение — сразу над ней, каждое следующее — строкой выше. Поэтому от
    подписей идём вверх, пока в графе `Изм.` стоит номер, и берём самый
    верхний. Пустые строки пропускаются (заготовки), любой другой текст
    (должность исполнителя, наименование) останавливает просмотр.
    """
    anchor = find_change_label_row(rows)
    if anchor < 0:
        return -1
    best_index = -1
    best_number = -1
    first = max(anchor - _MAX_CHANGE_ROWS, 0)
    for index in range(anchor - 1, first - 1, -1):
        value = _row_value(rows, index, 1)
        if value in ("", "-", "—", "–"):
            continue
        if not _CHANGE_NUMBER_RE.match(value):
            break
        number = int(value)
        if number > best_number:
            best_index, best_number = index, number
    return best_index


def _column_shift(rows: list[list[str]]) -> int:
    """Насколько сетка бланка сдвинута по столбцам относительно описания.

    В части бланков подпись `Лист` объединена на два столбца, и все столбцы
    справа уезжают на один вправо. Определяется по подписи в 1-м столбце:
    `Лист` вместо `Изм.` означает сдвиг на 1.
    """
    label = change_label_of(rows, 1).replace(".", "").replace(" ", "").lower()
    if label == "лист":
        return 1
    return 0


def read_revision_date(rows: list[list[str]]) -> str:
    """Дата изменения из графы `Дата`.

    Сначала берётся графа изменений (строка над подписями). Если она пуста
    (изменение не оформлялось), используется дата ближайшей подписанной
    строки исполнителей — это дата выпуска документа. Последний вариант —
    любая дата в столбце: в разных бланках строки исполнителей сдвинуты.
    """
    row_number, column_number = STAMP_CELLS[LABEL_DATE]
    if 1 < column_number <= _SHIFTABLE_COLUMNS:
        column_number += _column_shift(rows)
    candidates = []
    latest = latest_change_row(rows)
    if latest >= 0:
        # Дата последнего изменения — в той же строке, что и его номер.
        candidates.append(_row_value(rows, latest, column_number))
    candidates.append(anchored_cell(rows, row_number, column_number))
    anchor = find_change_label_row(rows)
    for offset in (1, 2, 3, 4):
        candidates.append(_row_value(rows, anchor - offset, column_number))
        candidates.append(_row_value(rows, anchor + offset, column_number))
    for text in candidates:
        parsed = parse_revision_date(text)
        if parsed:
            return parsed
    return ""


def read_stamp_values(rows: list[list[str]]) -> dict[str, str]:
    """Реквизиты штампа по координатной сетке из описания штампа.

    `STAMP_CELLS` задаёт пары (строка, столбец); в таблицу передаётся
    строка и столбец именно в таком порядке. `Лист` и `Листов` ищутся
    отдельно: в бланках они делят строку с подписями граф изменений.
    Пустая графа `Изм.` — это ноль: в бланках без выпущенных изменений
    строка значений не заполняется.
    """
    values: dict[str, str] = {}
    shift = _column_shift(rows)
    for code in STAMP_CELLS:
        if code in (LABEL_SHEET, LABEL_SHEETS):
            continue
        row_number, column_number = STAMP_CELLS[code]
        if shift and 1 < column_number <= _SHIFTABLE_COLUMNS:
            column_number += shift
        values[code] = anchored_cell(rows, row_number, column_number)
    values[LABEL_SHEET], values[LABEL_SHEETS] = read_sheet_values(rows)
    values[LABEL_DOC_CODE] = find_doc_code(rows)
    revision_row, revision_column = STAMP_CELLS[LABEL_REVISION]
    revision = anchored_cell(rows, revision_row, revision_column)
    latest = latest_change_row(rows)
    if latest >= 0:
        revision = _row_value(rows, latest, 1)
    values[LABEL_REVISION] = _revision_value(revision) if revision else "0"
    _apply_anchor_blocks(rows, values)
    return values


def _apply_anchor_blocks(rows: list[list[str]], values: dict[str, str]) -> None:
    """Наименование, стадия и организация по отсчёту от строки подписей.

    В колонтитулах правый блок стоит так: наименование документа — со строки
    после подписей (столбец 7), подпись `Стадия` — там же (столбец 8),
    значение стадии — ещё строкой ниже, организация — следом. Число строк
    выше подписей меняется, поэтому сетка снизу здесь не годится.
    """
    anchor = find_change_label_row(rows)
    if anchor < 0 or anchor + 2 >= len(rows):
        return
    stage = clean_text(_row_value(rows, anchor + 2, 8))
    if _is_value(stage) and len(stage) <= 3:
        values[LABEL_STAGE] = stage
    else:
        stage = ""
    # Значение стадии объединено вниз (vMerge) и повторяется в следующей
    # строке, поэтому организация — первое значение, не равное стадии.
    for index in range(anchor + 3, len(rows)):
        organization = clean_text(_row_value(rows, index, 8))
        if not _is_value(organization) or organization.startswith("Заказчик"):
            continue
        if organization == stage or len(organization) <= 3:
            continue
        values[LABEL_ORGANIZATION] = organization
        break
    values.update(read_title_blocks(rows))


def _title_column_blocks(rows: list[list[str]]) -> list[str]:
    """Различные вертикальные блоки столбца 7 по всей высоте штампа.

    «Заказчик…» и шифр в счёт не идут: остаются объект, титул, документ.
    Одинаковые соседние строки (vMerge) считаются одним блоком.
    """
    blocks: list[str] = []
    for row in rows:
        text = clean_text(row[6]) if len(row) > 6 else ""
        if not text or text.startswith("Заказчик"):
            continue
        if looks_like_doc_code(text) or is_bare_doc_code(text):
            continue
        if not blocks or blocks[-1] != text:
            blocks.append(text)
    return blocks


def detect_stamp_profile(rows: list[list[str]]) -> str:
    """Определяет раскладку штампа по числу блоков в колонке названий.

    Полный штамп (ИСВН): объект, титул и документ — три отдельных блока.
    Короткий (ЭС1): один блок, где титул и документ слиты. Прочее — UNKNOWN.
    """
    count = len(_title_column_blocks(rows))
    if count == 3:
        return STAMP_PROFILE_FULL
    if count == 1:
        return STAMP_PROFILE_SHORT
    return STAMP_PROFILE_UNKNOWN


def read_title_blocks(rows: list[list[str]]) -> dict[str, str]:
    """Объект, титул и наименование документа по профилю штампа.

    Полный профиль читает три ячейки. Короткий делит единственный блок:
    титул — начало «N этап строительства», остальное — документ. В
    неизвестной раскладке поля остаются пустыми, профиль возвращается
    в `stamp_profile`.
    """
    profile = detect_stamp_profile(rows)
    result = {LABEL_OBJECT: "", LABEL_TITLE: "", LABEL_DOCUMENT: "", LABEL_PROFILE: profile}
    blocks = _title_column_blocks(rows)
    if profile == STAMP_PROFILE_FULL:
        result[LABEL_OBJECT], result[LABEL_TITLE], result[LABEL_DOCUMENT] = blocks
    elif profile == STAMP_PROFILE_SHORT:
        match = STAGE_TITLE_RE.match(blocks[0])
        if match and match.group(2):
            result[LABEL_TITLE], result[LABEL_DOCUMENT] = match.group(1), match.group(2)
        else:
            result[LABEL_TITLE] = blocks[0]
    return result


def read_executors(rows: list[list[str]]) -> list[dict[str, str]]:
    """Исполнители из строк под подписями граф: должность, ФИО, подпись, дата."""
    anchor = find_change_label_row(rows)
    if anchor < 0:
        return []
    executors: list[dict[str, str]] = []
    pending_position = ""
    for row in rows[anchor + 1 :]:
        if len(row) < 6:
            continue
        position, name = clean_text(row[0]), clean_text(row[2])
        if position and not name:
            # должность без ФИО: ФИО может стоять строкой ниже
            pending_position = position
            continue
        if name and not position:
            position, pending_position = pending_position, ""
        else:
            pending_position = ""
        if not position or not name:
            continue
        executors.append(
            {
                "position": position,
                "name": name,
                "signature": clean_text(row[4]),
                "date": clean_text(row[5]),
            }
        )
    return executors


def _collapse_table(rows: list[list[str]]) -> list[list[str]]:
    """Схлопывает подряд идущие одинаковые значения в строке (для stamp_raw).

    Объединённые ячейки разворачиваются в сетку и дают много копий;
    для отладки достаточно одной. Пустые значения не схлопываются.
    """
    collapsed = []
    for row in rows:
        out: list[str] = []
        for cell in row:
            if out and cell and cell == out[-1]:
                continue
            out.append(cell)
        collapsed.append(out)
    return collapsed


def parse_stamp(file_path: str) -> dict[str, Any]:
    """Разбирает штамп документа и возвращает его реквизиты.

    Ключи результата: `doc_code`, `project_code`, `section_code`, `doc_type`,
    `revision`, `revision_date`, `sheet`, `sheets_total`, `stamp_raw`,
    `stamp_status`.
    """
    filename = os.path.basename(file_path)
    result: dict[str, Any] = {
        "doc_code": "",
        "project_code": "",
        "section_code": "",
        "doc_type": "",
        "revision": "0",
        "revision_date": None,
        "revision_date_source": "",
        "sheet": None,
        "sheets_total": None,
        "stage": "",
        "organization": "",
        "object_name": "",
        "title": "",
        "document_name": "",
        "stamp_profile": STAMP_PROFILE_UNKNOWN,
        "executors": [],
        "filename_dates": find_dates_in_filename(filename),
        "discrepancies": [],
        "stamp_raw": "",
        "stamp_status": STAMP_MISSING,
    }

    tables: list[list[list[str]]] = []
    values: dict[str, str] = {}
    try:
        tables = read_stamp_tables(file_path)
    except Exception:  # noqa: BLE001
        tables = []

    # В одном колонтитуле бывает несколько таблиц штампа (промежуточные
    # листы). Значение берётся из самой полной таблицы: пустые заготовки
    # (`Изм.` = 0) не должны перебивать реальные данные.
    best: dict[str, Any] = {"score": -1, "values": {}, "date": "", "executors": []}
    for rows in tables:
        table_values = read_stamp_values(rows)
        executors = read_executors(rows)
        score = sum(1 for text in table_values.values() if text) + len(executors)
        if score > best["score"]:
            best = {
                "score": score,
                "values": table_values,
                "date": read_revision_date(rows),
                "executors": executors,
            }
    values = best["values"] or {}
    if not values.get(LABEL_REVISION):
        values[LABEL_REVISION] = "0"

    result["stamp_raw"] = json.dumps(
        {"values": values, "tables": [_collapse_table(rows) for rows in tables]},
        ensure_ascii=False,
    )

    doc_code = values.get(LABEL_DOC_CODE, "")
    if not (is_doc_code(doc_code) or is_bare_doc_code(doc_code)):
        # Штампа нет: дата берётся из имени файла (неофициальный выпуск).
        result["revision_date"], result["revision_date_source"] = fallback_revision_date(file_path)
        return result

    parsed = parse_doc_code(doc_code)
    result["doc_code"] = parsed["doc_code"]
    result["project_code"] = parsed["project_code"]
    result["section_code"] = parsed["section_code"]
    # Шифр без типа документа получает тип по умолчанию.
    result["doc_type"] = normalize_doc_type(parsed["doc_type"] or DEFAULT_DOC_TYPE)

    result["revision"] = values.get(LABEL_REVISION, "") or "0"
    result["stage"] = values.get(LABEL_STAGE, "")
    result["organization"] = values.get(LABEL_ORGANIZATION, "")
    result["object_name"] = values.get(LABEL_OBJECT, "")
    result["title"] = values.get(LABEL_TITLE, "")
    result["document_name"] = values.get(LABEL_DOCUMENT, "")
    if result["doc_type"] == UNKNOWN_DOC_TYPE:
        # Тип в шифре не указан: определяем по наименованию документа («Кабельный журнал» -> КЖ).
        result["doc_type"] = doc_type_from_name(result["document_name"]) or result["doc_type"]
    result["stamp_profile"] = values.get(LABEL_PROFILE, "") or STAMP_PROFILE_UNKNOWN
    result["executors"] = best["executors"]

    revision_date = best["date"] or parse_revision_date(values.get(LABEL_DATE, ""))
    date_source = "stamp"
    if not revision_date:
        revision_date, date_source = fallback_revision_date(file_path)
    stamp_date = revision_date
    # Дата в имени файла новее даты штампа — она и есть дата изменения.
    name_date = newest_filename_date(filename)
    if name_date and (not revision_date or name_date > revision_date):
        revision_date, date_source = name_date, "filename"
    result["revision_date"] = revision_date
    result["revision_date_source"] = date_source
    # Дата изменения (комплекта): из штампа, без учёта даты в имени файла.
    result["stamp_date"] = stamp_date

    sheet, sheet_part = _sheet_numbers(values.get(LABEL_SHEET, ""))
    total = _to_int(values.get(LABEL_SHEETS, ""))
    if sheet == 0 and sheet_part is not None:
        sheet = sheet_part
    if sheet is not None and total is None:
        total = sheet
    result["sheet"] = sheet
    result["sheets_total"] = total

    result["filename_dates"] = find_dates_in_filename(filename)
    result["discrepancies"] = compare_with_filename(filename, result["revision"], stamp_date)

    result["stamp_status"] = STAMP_OK if revision_date else STAMP_PARTIAL
    return result
