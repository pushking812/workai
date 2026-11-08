"""Прогон find_best_match по заголовкам реальных CSV (только чтение).

Использование: python scripts/probe_headers.py <папка_с_CSV>
Справочник берётся из временной БД, рабочие БД не затрагиваются.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import database  # noqa: E402
from core.transformer.fuzzy_matcher import find_best_match  # noqa: E402


def main(folder: str) -> None:
    headers: Counter[str] = Counter()
    for path in sorted(Path(folder).glob("*.csv")):
        with open(path, encoding="utf-8-sig", newline="") as handle:
            first = next(csv.reader(handle, delimiter=";"), [])
        headers.update(h for h in first if h.strip())

    with tempfile.TemporaryDirectory() as tmp:
        connection = database.init_db(str(Path(tmp) / "probe.db"))
        rows = []
        for header, count in headers.most_common():
            result = find_best_match(connection, header)
            rows.append((header, count, result))
        connection.close()

    for header, count, r in rows:
        mark = "REVIEW" if r["requires_manual_review"] else "ok"
        print(
            f"{mark:6} {r['score']:5} {r.get('method', 'exact' if r['is_exact_match'] else 'fuzzy'):12} "
            f"{count:3}x {header[:60]!r} -> {r['suggested_canonical']}"
        )


if __name__ == "__main__":
    main(sys.argv[1])
