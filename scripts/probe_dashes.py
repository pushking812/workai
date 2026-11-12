"""Проба: ячейки с «--» после разбора (артефакт docx2python).

Запуск: python scripts/probe_dashes.py <папка> [макс. файлов с примерами]
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402

folder = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
shown = 0
total = 0
for path in sorted(glob.glob(os.path.join(folder, "*.docx"))):
    with numbering_fixed(path) as readable:
        hits = []
        for table in extract_tables_from_docx(readable):
            for row in table:
                for ci, cell in enumerate(row):
                    if "--" in str(cell):
                        hits.append((ci, repr(cell)[:60]))
    if hits:
        total += 1
        if shown < limit:
            shown += 1
            print(os.path.basename(path), len(hits), hits[:6])
print("файлов с '--':", total)
