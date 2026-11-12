"""Где в таблицах docx номер строки записан со скобкой (`18)`) и какие таблицы без шапки.

Использование:
    python scripts/probe_paren.py [--out data/exports/probes] [папка, по умолчанию ВОР]

Папка обходится с вложенными; читаются только .docx. В консоль печатаются ход
работы, найденные таблицы и итог. В `paren_<папка>.xlsx` те же находки
(файл, таблица, есть ли шапка, число и примеры номеров); файлы с ошибкой
перечислены ниже с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.header_profiles import parse_table  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, Progress, list_documents, print_plan, print_summary,
    reason_of, write_workbook,
)

PATTERN = re.compile(r"^\s*\d+\)\s*$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", nargs="?", default="ВОР")
    parser.add_argument("--out", default="data/exports/probes")
    args = parser.parse_args()
    out_dir = Path(args.out)

    if not Path(args.folder).is_dir():
        print_plan("Папки", [(args.folder, None)], out_dir)
        print("Нечего обрабатывать.")
        return
    files = list_documents(args.folder, recursive=True, extensions=(".docx",))
    print_plan("Папки", [(args.folder, len(files))], out_dir)

    progress = Progress(len(files))
    rows: list[list] = []
    problems: list[tuple[str, str, str]] = []
    for number, path in enumerate(files, 1):
        progress.step(args.folder, number, len(files), path.name)
        found: list[list] = []
        try:
            for index, table in enumerate(extract_tables_from_docx(str(path)), start=1):
                if not table:
                    continue
                hits = [str(row[0]).strip() for row in table if row and PATTERN.match(str(row[0]))]
                if hits:
                    no_header = not any(parse_table(table).headers)
                    found.append([str(path), index, "да" if no_header else "нет", len(hits),
                                  ", ".join(hits[:5]) + ("..." if len(hits) > 5 else "")])
        except Exception as error:  # noqa: BLE001
            reason = reason_of(error)
            problems.append((MARK_ERROR, path.name, reason))
            progress.note("ОШИБКА: " + reason)
            continue
        for item in found:
            print(f"{item[0]} | таблица {item[1]} | без шапки: {item[2] == 'да'} | "
                  f"номера: {item[4]} ({item[3]})")
        rows += found

    result = write_workbook(out_dir / ("paren_%s.xlsx" % Path(args.folder).name), [{
        "title": "Номера со скобкой",
        "header": ["Файл", "Таблица", "Без шапки", "Номеров", "Примеры номеров"],
        "rows": rows, "problems": problems, "freeze": "A2", "widths": {1: 80, 5: 40},
    }])
    line = "%s: обработано %d из %d, таблиц со скобкой %d -> %s" % (
        args.folder, len(files) - len(problems), len(files), len(rows), result)
    print_summary([line], [(args.folder, *p) for p in problems],
                  len(files) - len(problems), len(files), out_dir)


if __name__ == "__main__":
    main()
