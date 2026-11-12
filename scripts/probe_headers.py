"""Прогон find_best_match по заголовкам реальных CSV (только чтение).

Использование:
    python scripts/probe_headers.py [--out data/exports/probes] <папка_с_CSV>

Справочник берётся из временной БД, рабочие БД не затрагиваются.
В консоль печатаются ход работы, строки «статус оценка метод частота заголовок ->
каноническое» и итог. В `headers_match_<папка>.xlsx` те же строки; CSV, которые
не прочитались или пусты, перечислены ниже с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import database  # noqa: E402
from core.transformer.fuzzy_matcher import find_best_match  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, MARK_SKIPPED, Progress, list_documents, print_plan,
    print_summary, reason_of, write_workbook,
)

HEADER = ["Статус", "Оценка", "Метод", "Встречается", "Заголовок", "Каноническое имя"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", help="папка с CSV")
    parser.add_argument("--out", default="data/exports/probes")
    args = parser.parse_args()
    out_dir = Path(args.out)

    folder = Path(args.folder)
    if not folder.is_dir():
        print_plan("Папки", [(args.folder, None)], out_dir)
        print("Нечего обрабатывать.")
        return
    files = list_documents(args.folder, extensions=(".csv",))
    print_plan("Папки", [(args.folder, len(files))], out_dir)

    progress = Progress(len(files))
    headers: Counter[str] = Counter()
    problems: list[tuple[str, str, str]] = []
    for number, path in enumerate(files, 1):
        progress.step(folder.name, number, len(files), path.name)
        try:
            with open(path, encoding="utf-8-sig", newline="") as handle:
                first = next(csv.reader(handle, delimiter=";"), [])
        except Exception as error:  # noqa: BLE001
            reason = reason_of(error)
            problems.append((MARK_ERROR, path.name, reason))
            progress.note("ОШИБКА: " + reason)
            continue
        names = [h for h in first if h.strip()]
        if not names:
            reason = "нет строки заголовков (первая строка пуста)"
            problems.append((MARK_SKIPPED, path.name, reason))
            progress.note("НЕ ОБРАБОТАН: " + reason)
            continue
        headers.update(names)

    with tempfile.TemporaryDirectory() as tmp:
        connection = database.init_db(str(Path(tmp) / "probe.db"))
        results = [(h, n, find_best_match(connection, h)) for h, n in headers.most_common()]
        connection.close()

    rows: list[list] = []
    review = 0
    for header, count, r in results:
        mark = "REVIEW" if r["requires_manual_review"] else "ok"
        review += mark == "REVIEW"
        method = r.get("method", "exact" if r["is_exact_match"] else "fuzzy")
        print(f"{mark:6} {r['score']:5} {method:12} {count:3}x {header[:60]!r} -> {r['suggested_canonical']}")
        rows.append([mark, r["score"], method, count, header, r["suggested_canonical"]])

    result = write_workbook(out_dir / ("headers_match_%s.xlsx" % folder.name), [{
        "title": "Заголовки", "header": HEADER, "rows": rows, "problems": problems,
        "freeze": "A2", "widths": {5: 60, 6: 36},
    }])
    line = "%s: обработано %d из %d, разных заголовков %d, на ручную проверку %d -> %s" % (
        folder.name, len(files) - len(problems), len(files), len(rows), review, result)
    print_summary([line], [(folder.name, *p) for p in problems],
                  len(files) - len(problems), len(files), out_dir)


if __name__ == "__main__":
    main()
