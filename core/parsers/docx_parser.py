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
from dataclasses import dataclass
from typing import Any

from docx2python import docx2python

from core.transformer.schema_analyzer import normalize_header

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


def _is_banner_row(row: list[str]) -> bool:
    """Заголовок документа на всю ширину таблицы («ВЕДОМОСТЬ ОБЪЁМОВ РАБОТ»).

    docx2python повторяет объединённую ячейку в каждой колонке; это название
    таблицы, а не уровень шапки.
    """
    if len(row) < 3 or not all(row):
        return False
    return len({cell.casefold() for cell in row}) == 1


def _is_data_row(row: list[str]) -> bool:
    """Строка данных: первая заполненная ячейка — номер позиции («1», «2.»)."""
    for cell in row:
        if cell:
            return cell.strip().rstrip(".)").isdigit()
    return False


def _next_is_data(table: list[list[str]], index: int, width: int) -> bool:
    """Следующая непустая строка после `index` — строка данных."""
    for row in table[index + 1:index + 4]:
        padded = list(row) + [""] * (width - len(row))
        if not _is_empty_row(padded):
            return _is_data_row(padded)
    return False


def _collapse_repeats(parts: list[str]) -> list[str]:
    """Убирает подряд идущие одинаковые уровни шапки (объединённые ячейки)."""
    out: list[str] = []
    for part in parts:
        if not out or out[-1].casefold() != part.casefold():
            out.append(part)
    return out


LEVEL_SEPARATOR = "|"


@dataclass
class HeaderScan:
    """Результат разбора шапки до склейки уровней."""

    levels: list[list[str]]  # уровни каждой колонки (сырые, без схлопывания)
    positions: list[list[int]]  # номера строк шапки, из которых взяты уровни
    header_rows: int  # сколько строк заняла шапка
    data_start: int
    group_prefix: str
    hierarchical: bool  # есть объединение ячеек по горизонтали над колонками

    @property
    def width(self) -> int:
        return len(self.levels)

    def is_orphan(self, index: int) -> bool:
        """Колонка без родительских уровней: в шапке есть только последняя строка или ничего.

        Это артефакт сетки docx (лишняя ячейка в нижней строке шапки).
        """
        if not self.hierarchical or self.header_rows < 2:
            return False
        positions = self.positions[index]
        return not positions or (len(positions) == 1 and positions[0] == self.header_rows - 1)


def scan_headers(table: list[list[str]]) -> HeaderScan:
    """Находит строки шапки и раскладывает их по колонкам."""
    if not table:
        return HeaderScan([], [], 0, 0, "", False)

    width = max(len(row) for row in table)
    levels: list[list[str]] = [[] for _ in range(width)]
    positions: list[list[int]] = [[] for _ in range(width)]
    used_rows: list[list[str]] = []
    group_prefix = ""
    data_start = len(table)

    for index, row in enumerate(table[:HEADER_SCAN_DEPTH]):
        normalised = list(row) + [""] * (width - len(row))
        if _is_empty_row(normalised):
            continue
        if is_numbering_row(normalised, width):
            data_start = index + 1
            break
        if _is_data_row(normalised):
            # Без уровней это таблица-продолжение (разрыв страницы): шапки нет.
            if not any(levels):
                data_start = index
            break
        if _is_banner_row(normalised):
            continue
        if _is_group_row(normalised):
            if any(levels) and _next_is_data(table, index, width):
                break  # группа раздела данных, а не префикс подзаголовков
            group_prefix = normalised[[i for i, c in enumerate(normalised) if c][0]]
            continue
        for column, cell in enumerate(normalised):
            if cell:
                levels[column].append(cell)
                positions[column].append(len(used_rows))
        used_rows.append(normalised)
        data_start = index + 1

    # Объединённая по горизонтали ячейка над колонками docx2python повторяет
    # в каждой покрытой колонке; смотрим все строки шапки, кроме нижней.
    hierarchical = any(
        row[i] and row[i].casefold() == row[i + 1].casefold()
        for row in used_rows[:-1]
        for i in range(width - 1)
    )
    return HeaderScan(levels, positions, len(used_rows), data_start, group_prefix, hierarchical)


def join_levels(scan: HeaderScan, index: int) -> str:
    """Имя колонки из её уровней.

    Иерархическая шапка: каждый уровень нормализуется (`normalize_header`),
    одинаковые подряд идущие уровни схлопываются, склейка через `|`.
    Плоская шапка (многострочные заголовки): уровни через пробел как есть.
    """
    parts = scan.levels[index]
    if scan.hierarchical:
        normalised = [normalize_header(part) for part in parts]
        if scan.group_prefix:
            normalised.insert(0, normalize_header(scan.group_prefix))
        return LEVEL_SEPARATOR.join(_collapse_repeats([part for part in normalised if part]))

    # docx2python повторяет текст объединённой ячейки в каждой покрытой
    # колонке/строке: подряд идущие одинаковые уровни схлопываем.
    parts = _collapse_repeats(parts)
    joined = " ".join(parts)
    if scan.group_prefix and joined:
        joined = f"{scan.group_prefix} {joined}"
    return joined


def extract_headers(table: list[list[str]]) -> tuple[list[str], int]:
    """Собирает шапку таблицы и возвращает её вместе с индексом первой строки данных.

    Строка нумерации колонок отбрасывается. Строка-группа не становится
    заголовком колонки: её текст запоминается как префикс для подзаголовков,
    которые идут ниже. Если над колонками есть объединённые ячейки
    (кабельный журнал), имя колонки — нормализованные уровни через `|`:
    `КабельПровод|ПоПроекту|Марка`.
    """
    scan = scan_headers(table)
    return [join_levels(scan, index) for index in range(scan.width)], scan.data_start


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
