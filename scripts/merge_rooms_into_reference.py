"""Переносит экспликации из data/exports/Помещения.xlsx в справочник:
`spravochniki.xlsx` (с резервной копией) и, если не указан --no-db, в базу приложения.

Новые этажи станций получают код ПС<N> («3 подземный этаж» -> ПС3), повтор номера на этаже —
суффикс « (#2)». Существующие значения не перезаписываются: заполняются только пустые
названия и площади.

Запуск (из venv проекта): python scripts/merge_rooms_into_reference.py [--no-db] [--no-xlsx]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import database, reference_exchange as ex  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", default=str(ROOT / "data" / "exports" / "Помещения.xlsx"))
    ap.add_argument("--reference", default=str(ROOT / "spravochniki.xlsx"))
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--no-xlsx", action="store_true")
    args = ap.parse_args()
    records = ex.records_from_rooms_xlsx(args.rooms)
    print(f"записей в экспликациях: {len(records)}")
    if not args.no_xlsx:
        backup = ROOT / "data" / "_pq_work" / "spravochniki.до_помещений.xlsx"
        if not backup.exists():
            shutil.copy2(args.reference, backup)
        print("spravochniki.xlsx:", ex.merge_into_spravochniki(args.reference, records))
    if not args.no_db:
        connection = database.init_db()
        try:
            print("БД:", ex.merge_into_db(connection, records))
        finally:
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
