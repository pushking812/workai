"""Общие функции скриптов: ход работы в консоли и отчёт в Excel.

Единый вид для всех скриптов (как в export_headers.py):
1. при запуске - какие папки/файлы приняты в обработку и куда пойдёт результат;
2. счётчик «обработано N из M» по ходу работы;
3. по окончании - итог, путь к папке результата;
4. файлы с ошибкой или без обработки - в консоли и в том же xlsx, с причиной.

Модуль только форматирует вывод и пишет xlsx, логики разбора документов в нём нет.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

SUPPORTED = (".doc", ".docx")
MARK_ERROR = "ОШИБКА"
MARK_SKIPPED = "НЕ ОБРАБОТАН"

_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_TITLE = re.compile(r"[\[\]:*?/\\]")

# Проблемный файл: (пометка, имя, причина).
Problem = tuple[str, str, str]


def list_documents(folder: str, recursive: bool = False, extensions=SUPPORTED) -> list[Path]:
    """Документы Word в папке по алфавиту; временные `~$` пропускаются."""
    root = Path(folder)
    found = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        (p for p in found
         if p.is_file() and p.suffix.lower() in extensions and not p.name.startswith("~$")),
        key=lambda p: str(p).lower(),
    )


def print_plan(kind: str, items: list[tuple[str, int | None]], out_dir: Path | str, stream=None) -> None:
    """Что принято в обработку. count=None - объекта нет, он пропускается."""
    stream = stream or sys.stdout
    print("%s к обработке:" % kind, file=stream)
    for name, count in items:
        if count is None:
            print("  %s - НЕТ ТАКОГО ОБЪЕКТА, пропуск" % name, file=stream)
        else:
            print("  %s (файлов: %d)" % (name, count), file=stream)
    print("Папка результата:", Path(out_dir).resolve(), file=stream, flush=True)


class Progress:
    """Счётчик «номер в группе / всего в группе (всего по всем группам)»."""

    def __init__(self, total: int, stream=None):
        self.total = total
        self.done = 0
        self.stream = stream or sys.stdout

    def step(self, group: str, number: int, count: int, name: str) -> None:
        self.done += 1
        print("  [%s] %d/%d (всего %d/%d) %s" % (
            group, number, count, self.done, self.total, name), file=self.stream, flush=True)

    def note(self, text: str) -> None:
        print("      " + text, file=self.stream, flush=True)


def _clean(value):
    return _ILLEGAL.sub("", value) if isinstance(value, str) else value


def _sheet_title(title: str, used: set[str]) -> str:
    base = (_BAD_TITLE.sub("_", title) or "Лист")[:31]
    name, n = base, 2
    while name in used:
        suffix = "_%d" % n
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


def write_workbook(path: Path | str, sheets: list[dict]) -> str:
    """Пишет xlsx и возвращает полный путь или текст о неудаче записи.

    Лист: {"title", "header": [...], "rows": [[...]], "problems": [Problem],
    "freeze": "A2", "widths": {номер_колонки: ширина}, "width": ширина по умолчанию}.
    Блок проблем идёт ниже данных, строки подсвечены красным.
    """
    target = Path(path)
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    fill = PatternFill("solid", fgColor="FFC7CE")
    for spec in sheets:
        ws = wb.create_sheet(_sheet_title(spec["title"], used))
        header = list(spec["header"])
        ws.append([_clean(h) for h in header])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in spec["rows"]:
            ws.append([_clean(v) for v in row])
        problems = spec.get("problems") or []
        if problems:
            ws.append([])
            ws.append(["Файлы с ошибкой или без обработки: %d" % len(problems)])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
            ws.append(["Пометка", "Файл", "Причина"])
            for cell in ws[ws.max_row]:
                cell.font = Font(bold=True)
            for mark, name, reason in problems:
                ws.append([_clean(mark), _clean(name), _clean(reason)])
                for cell in ws[ws.max_row][:3]:
                    cell.fill = fill
        if spec.get("freeze"):
            ws.freeze_panes = spec["freeze"]
        widths = spec.get("widths", {})
        columns = max(len(header), 3 if problems else 0)
        for index in range(1, columns + 1):
            ws.column_dimensions[get_column_letter(index)].width = widths.get(index, spec.get("width", 22))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(target)  # файл должен быть закрыт в Excel
    except PermissionError:
        return "НЕ ЗАПИСАН (файл открыт в Excel?): %s" % target
    return str(target.resolve())


def print_summary(
    lines: list[str],
    problems: list[tuple[str, str, str, str]],
    done_ok: int,
    total: int,
    out_dir: Path | str,
    stream=None,
) -> None:
    """Итог: сколько обработано, путь к результату, проблемные файлы по группам.

    problems: (группа, пометка, имя, причина).
    """
    stream = stream or sys.stdout
    print("\n=== Итог ===", file=stream)
    print("Обработано без проблем: %d из %d" % (done_ok, total), file=stream)
    print("Папка с результатом:", Path(out_dir).resolve(), file=stream)
    for line in lines:
        print(line, file=stream)
    if problems:
        print("Проблемные файлы:", file=stream)
        for group, mark, name, reason in problems:
            print("  [%s] %s: %s - %s" % (group, mark, name, reason), file=stream)
    else:
        print("Проблемных файлов нет.", file=stream)
    stream.flush()


def reason_of(error: Exception, limit: int = 150) -> str:
    return "%s: %s" % (type(error).__name__, str(error)[:limit])
