"""Парсер DOCX: извлечение таблиц, сборка шапки и экспорт в CSV (Этап 1.3).

Особенности реальных ВОР:
* шапка бывает многострочной, внутри одной ячейки заголовок разбит на
  несколько абзацев (`["№", "п/п"]` -> `"№ п/п"`);
* вторая строка шапки часто содержит нумерацию колонок (`1, 2, 3, ...`);
* над колонками встречаются строки-группы (`Оборудование`, `Подсистема ...`),
  объединённые по горизонтали.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Any

from docx2python import docx2python

HEADER_SCAN_DEPTH = 3
MEDIA_RE = re.compile(r"^-+media/[^-]+-+")


def clean_cell_text(cell: Any) -> str:
    """Рекурсивно склеивает куски ячейки в одну строку без переносов и табуляций."""
    if cell is None:
        return ""
    if isinstance(cell, (list, tuple)):
        parts = [clean_cell_text(item) for item in cell]
        text = " ".join(part for part in parts if part)
    else:
        text = str(cell)
    text = MEDIA_RE.sub("", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_tables_from_docx(file_path: str) -> list[list[list[str]]]:
    """Возвращает все таблицы документа: [Таблица][Строка][Ячейка]."""
    document = docx2python(file_path)
    try:
        tables: list[list[list[str]]] = []
        # body: [таблица][строка][ячейка][абзац]; абзацы вне таблиц — это
        # «таблицы» 1x1, их отбрасывает _looks_like_table.
        for table in _as_list(document.body):
            if not _looks_like_table(table):
                continue
            rows = [[clean_cell_text(cell) for cell in row] for row in table]
            if any(any(cell for cell in row) for row in rows):
                tables.append(rows)
        return tables
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _looks_like_table(table: Any) -> bool:
    if not isinstance(table, list) or not table:
        return False
    if not all(isinstance(row, list) for row in table):
        return False
    return len(table[0]) > 1 or len(table) > 1


def _is_empty_row(row: list[str]) -> bool:
    return not any(cell for cell in row)


def is_numbering_row(row: list[str], width: int | None = None) -> bool:
    """Строка нумерации колонок: `1, 2, 3, ...` по возрастанию."""
    cells = [cell for cell in row if cell]
    if len(cells) < 2:
        return False
    numbers: list[int] = []
    for cell in cells:
        text = cell.strip().rstrip(".").strip()
        if not text.isdigit() or len(text) > 3:
            return False
        numbers.append(int(text))
    total = width if width is not None else len(row)
    if len(numbers) < max(2, total // 2):
        return False
    return numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def _is_group_row(row: list[str], header_start: int | None = None) -> bool:
    """Строка-группа: одна заполненная ячейка, остальные пустые."""
    filled = [(index, cell) for index, cell in enumerate(row) if cell]
    if len(filled) != 1:
        return False
    index, text = filled[0]
    if index == 0:
        return False
    return len(text) >= 2


def _is_data_row(row: list[str]) -> bool:
    """Строка данных: первая заполненная ячейка — номер позиции («1», «2.»)."""
    for cell in row:
        if cell:
            return cell.strip().rstrip(".").isdigit()
    return False


def extract_headers(table: list[list[str]]) -> tuple[list[str], int]:
    """Собирает шапку таблицы и возвращает её вместе с индексом первой строки данных.

    Строка нумерации колонок отбрасывается. Строка-группа не становится
    заголовком колонки: её текст запоминается как префикс для подзаголовков,
    которые идут ниже.
    """
    if not table:
        return [], 0

    width = max(len(row) for row in table)
    headers: list[list[str]] = [[] for _ in range(width)]
    group_prefix = ""
    data_start = len(table)

    for index, row in enumerate(table[:HEADER_SCAN_DEPTH]):
        normalised = list(row) + [""] * (width - len(row))
        if _is_empty_row(normalised):
            continue
        if is_numbering_row(normalised, width):
            data_start = index + 1
            break
        if any(headers) and _is_data_row(normalised):
            break
        if _is_group_row(normalised):
            group_prefix = normalised[[i for i, c in enumerate(normalised) if c][0]]
            continue
        headers = [headers[i] + ([cell] if cell else []) for i, cell in enumerate(normalised)]
        data_start = index + 1

    result: list[str] = []
    for parts in headers:
        if len(parts) > 1:
            # Соседние заголовки-родитель/подзаголовок («Родитель Подзаголовок»).
            joined = " ".join(parts)
        else:
            joined = parts[0] if parts else ""
        if group_prefix and joined:
            joined = f"{group_prefix} {joined}"
        elif group_prefix and not joined:
            joined = ""
        result.append(joined)
    return result, data_start


def save_table_to_csv(
    table_data: list[list[str]],
    output_path: str,
    headers: list[str] | None = None,
    data_start: int | None = None,
) -> str:
    """Сохраняет таблицу в CSV в кодировке utf-8-sig (для Excel)."""
    parent = os.path.dirname(os.path.abspath(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    rows = table_data
    if data_start is not None:
        rows = table_data[data_start:]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        if headers is not None:
            writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return output_path
