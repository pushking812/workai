"""Отброшенные колонки таблиц .docx/.doc (только чтение).

Использование:
    python scripts/probe_dropped.py [--out data/exports/probes] <файл|папка> [...]

Для каждой таблицы: число колонок в документе, профиль, итоговые заголовки,
отброшенные колонки (`dropped`) и первые 6 строк. Помогает проверять правило
отбрасывания колонок «Проложен». В консоль печатаются ход работы и итог; в
`dropped.xlsx` листы «Таблицы» и «Первые строки», файлы с ошибкой перечислены на
листе «Таблицы» ниже с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.doc_converter import read_doc_stamp_source  # noqa: E402
from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.header_profiles import parse_table  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from scripts.dump_table_head import expand  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, Progress, print_plan, print_summary, reason_of, write_workbook,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="файлы или папки")
    parser.add_argument("--out", default="data/exports/probes")
    args = parser.parse_args()
    out_dir = Path(args.out)

    files, plan = expand(args.paths)
    print_plan("Файлы и папки", plan, out_dir)
    progress = Progress(len(files))
    table_rows: list[list] = []
    head_rows: list[list] = []
    problems: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory() as cache:
        for number, path in enumerate(files, 1):
            progress.step("файл", number, len(files), path.name)
            try:
                source = read_doc_stamp_source(str(path), cache)
                with numbering_fixed(source) as readable:
                    tables = extract_tables_from_docx(readable)
                parsed_all = [(t, parse_table(t)) for t in tables]
            except Exception as error:  # noqa: BLE001
                reason = reason_of(error)
                problems.append((MARK_ERROR, path.name, reason))
                progress.note("ОШИБКА: " + reason)
                continue
            for index, (t, p) in enumerate(parsed_all, 1):
                cols = max((len(r) for r in t), default=0)
                print("cols in doc:", cols, "profile:", getattr(p, "profile", None))
                print("headers:", p.headers)
                print("dropped:", p.dropped)
                for r in t[:6]:
                    print(r)
                print("rows:", len(t))
                table_rows.append([
                    path.name, index, cols, getattr(p, "profile", None),
                    " ; ".join(str(h) for h in p.headers), str(p.dropped), len(t),
                ])
                for row_index, r in enumerate(t[:6]):
                    head_rows.append([path.name, index, row_index, *r])

    width = max((len(r) - 3 for r in head_rows), default=0)
    result = write_workbook(out_dir / "dropped.xlsx", [
        {"title": "Таблицы",
         "header": ["Файл", "Таблица", "Колонок в документе", "Профиль", "Заголовки", "Отброшено", "Строк"],
         "rows": table_rows, "problems": problems, "freeze": "A2", "widths": {1: 48, 5: 70, 6: 30}},
        {"title": "Первые строки",
         "header": ["Файл", "Таблица", "Строка"] + ["Ячейка %d" % i for i in range(1, width + 1)],
         "rows": head_rows, "freeze": "D2", "widths": {1: 48}},
    ])
    print_summary(["Excel: " + result], [("файл", *p) for p in problems],
                  len(files) - len(problems), len(files), out_dir)


if __name__ == "__main__":
    main()
