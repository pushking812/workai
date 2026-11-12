"""Сводка заголовков таблиц docx в папке: сколько раз встречается каждый и таблицы без шапки.

Использование:
    python scripts/probe_nohdr.py [--out data/exports/probes] [папка, по умолчанию ВОР]

Папка обходится с вложенными; читаются только .docx. В консоль печатаются ход
работы, число файлов, таблиц без шапки и 40 самых частых заголовков. В
`nohdr_<папка>.xlsx` листы «Заголовки» (все заголовки с частотой) и «Без шапки»
(по файлам); файлы с ошибкой перечислены на листе «Заголовки» ниже с пометкой
и причиной.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.header_profiles import parse_table  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, Progress, list_documents, print_plan, print_summary,
    reason_of, write_workbook,
)


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
    counter: Counter = Counter()
    no_header = 0
    nohdr_rows: list[list] = []
    problems: list[tuple[str, str, str]] = []
    for number, path in enumerate(files, 1):
        progress.step(args.folder, number, len(files), path.name)
        try:
            tables = extract_tables_from_docx(str(path))
            local_counter: Counter = Counter()
            local_nohdr = 0
            total = 0
            for table in tables:
                if not table:
                    continue
                total += 1
                headers = parse_table(table).headers
                if not any(headers):
                    local_nohdr += 1
                local_counter.update(h for h in headers if h)
        except Exception as error:  # noqa: BLE001
            reason = reason_of(error)
            problems.append((MARK_ERROR, path.name, reason))
            progress.note("ОШИБКА: " + reason)
            continue
        counter.update(local_counter)  # в сводку попадают только прочитанные файлы
        no_header += local_nohdr
        if local_nohdr:
            nohdr_rows.append([str(path), total, local_nohdr])

    print(len(files), "files; tables without header:", no_header)
    for header, count in counter.most_common(40):
        print(count, header[:90])

    result = write_workbook(out_dir / ("nohdr_%s.xlsx" % Path(args.folder).name), [
        {"title": "Заголовки", "header": ["Встречается", "Заголовок"],
         "rows": [[n, h] for h, n in counter.most_common()], "problems": problems,
         "freeze": "A2", "widths": {1: 14, 2: 90}},
        {"title": "Без шапки", "header": ["Файл", "Таблиц", "Из них без шапки"],
         "rows": nohdr_rows, "freeze": "A2", "widths": {1: 80}},
    ])
    line = "%s: обработано %d из %d, таблиц без шапки %d, разных заголовков %d -> %s" % (
        args.folder, len(files) - len(problems), len(files), no_header, len(counter), result)
    print_summary([line], [(args.folder, *p) for p in problems],
                  len(files) - len(problems), len(files), out_dir)


if __name__ == "__main__":
    main()
