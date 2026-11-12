"""Первые строки сырых таблиц файлов (только чтение).

Использование:
    python scripts/dump_table_head.py [--rows 8] [--out data/exports/dumps] <файл|папка> [...]

Старая форма `python scripts/dump_table_head.py <файл> 8` тоже работает.
В консоль печатаются первые строки каждой таблицы (ячейки обрезаны до 22
знаков), ход работы и итог. В `table_heads.xlsx` те же строки с полным текстом
ячеек: лист на файл и лист «Итог»; файлы, которые не удалось прочитать,
перечислены на листе «Итог» с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.doc_converter import read_doc_stamp_source  # noqa: E402
from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, Progress, list_documents, print_plan, print_summary,
    reason_of, write_workbook,
)


def expand(paths: list[str]) -> tuple[list[Path], list[tuple[str, int | None]]]:
    """Файлы к обработке и список «объект - число файлов» для вывода плана."""
    files: list[Path] = []
    plan: list[tuple[str, int | None]] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            found = list_documents(item)
            files += found
            plan.append((item, len(found)))
        elif path.is_file():
            files.append(path)
            plan.append((item, 1))
        else:
            plan.append((item, None))
    return files, plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="файлы или папки")
    parser.add_argument("--rows", type=int, default=8, help="строк на таблицу")
    parser.add_argument("--out", default="data/exports/dumps")
    args = parser.parse_args()
    limit, paths = args.rows, args.paths
    if len(paths) > 1 and paths[-1].isdigit():  # старая форма: <файл> <строк>
        limit, paths = int(paths[-1]), paths[:-1]
    out_dir = Path(args.out)

    files, plan = expand(paths)
    print_plan("Файлы и папки", plan, out_dir)
    progress = Progress(len(files))
    sheets: list[dict] = []
    status_rows: list[list] = []
    problems: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory() as cache:
        for number, path in enumerate(files, 1):
            progress.step("файл", number, len(files), path.name)
            try:
                source = read_doc_stamp_source(str(path), cache)
                with numbering_fixed(source) as readable:
                    tables = extract_tables_from_docx(readable)
            except Exception as error:  # noqa: BLE001
                reason = reason_of(error)
                problems.append((MARK_ERROR, path.name, reason))
                status_rows.append([path.name, "", MARK_ERROR])
                progress.note("ОШИБКА: " + reason)
                continue
            status_rows.append([path.name, len(tables), "ок"])
            rows: list[list] = []
            for table_number, table in enumerate(tables):
                print("-- таблица %d: строк %d" % (table_number, len(table)))
                for index, row in enumerate(table[:limit]):
                    print(index, [cell[:22] for cell in row])
                    rows.append([table_number, len(table), index, *row])
            width = max((len(r) - 3 for r in rows), default=0)
            sheets.append({
                "title": path.stem,
                "header": ["Таблица", "Строк в таблице", "Строка"] + ["Ячейка %d" % i for i in range(1, width + 1)],
                "rows": rows, "freeze": "D2", "width": 24,
            })
    sheets.append({"title": "Итог", "header": ["Файл", "Таблиц", "Статус"], "rows": status_rows,
                   "problems": problems, "widths": {1: 60}})
    result = write_workbook(out_dir / "table_heads.xlsx", sheets)
    print_summary(["Excel: " + result], [("файл", *p) for p in problems],
                  len(files) - len(problems), len(files), out_dir)


if __name__ == "__main__":
    main()
