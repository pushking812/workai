"""Сводка по БД: схемы, schema_hash, число CSV. Только чтение.

Использование:
    python scripts/probe_db_state.py [--out data/exports/probes] data\\app.db [другая.db ...]

В консоль печатаются ход работы (какие БД приняты, N из M), сводка по каждой БД
и итог. В `db_state.xlsx` листы «БД» и «Схемы»; БД, которые не открылись,
перечислены на листе «БД» ниже с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, MARK_SKIPPED, Progress, print_plan, print_summary,
    reason_of, write_workbook,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dbs", nargs="+", help="файлы БД")
    parser.add_argument("--out", default="data/exports/probes")
    args = parser.parse_args()
    out_dir = Path(args.out)

    print_plan("БД", [(db, 1 if Path(db).is_file() else None) for db in args.dbs], out_dir)
    progress = Progress(len(args.dbs))
    db_rows: list[list] = []
    schema_rows: list[list] = []
    problems: list[tuple[str, str, str]] = []
    for number, db in enumerate(args.dbs, 1):
        progress.step("БД", number, len(args.dbs), db)
        if not Path(db).is_file():
            problems.append((MARK_SKIPPED, db, "файл БД не найден"))
            progress.note("НЕ ОБРАБОТАН: файл БД не найден")
            continue
        try:
            c = sqlite3.connect("file:%s?mode=ro" % Path(db).resolve().as_posix(), uri=True)
            try:
                version = c.execute("pragma user_version").fetchone()[0]
                files = c.execute("select count(*) from files").fetchone()[0]
                no_hash = c.execute(
                    "select count(*) from files where schema_hash is null or schema_hash=''").fetchone()[0]
                schemas = c.execute("select count(*) from schemas").fetchone()[0]
                dist = c.execute(
                    "select s.schema_hash, count(f.id) from schemas s "
                    "left join files f on f.schema_hash=s.schema_hash "
                    "group by s.schema_hash order by 2 desc").fetchall()
            finally:
                c.close()
        except Exception as error:  # noqa: BLE001
            reason = reason_of(error)
            problems.append((MARK_ERROR, db, reason))
            progress.note("ОШИБКА: " + reason)
            continue
        print(db, "user_version =", version)
        print("  files:", files, "| без schema_hash:", no_hash)
        print("  schemas:", schemas)
        for row in dist:
            print("   ", row)
        db_rows.append([db, version, files, no_hash, schemas])
        schema_rows += [[db, h, n] for h, n in dist]

    result = write_workbook(out_dir / "db_state.xlsx", [
        {"title": "БД", "header": ["БД", "user_version", "Файлов", "Без schema_hash", "Схем"],
         "rows": db_rows, "problems": problems, "widths": {1: 40}},
        {"title": "Схемы", "header": ["БД", "schema_hash", "Файлов"], "rows": schema_rows,
         "freeze": "A2", "widths": {1: 40, 2: 70}},
    ])
    print_summary(["Excel: " + result], [("БД", *p) for p in problems],
                  len(args.dbs) - len(problems), len(args.dbs), out_dir)


if __name__ == "__main__":
    main()
