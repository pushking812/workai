"""Проба: первая колонка таблицы после исправления нумерации.

Запуск: python scripts/check_svor_numbers.py <файл.docx>
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402

with numbering_fixed(sys.argv[1]) as readable:
    print("исправленная копия:", readable != sys.argv[1])
    for i, table in enumerate(extract_tables_from_docx(readable)):
        col = [row[0] for row in table if row]
        print(i, len(table), col[:14], "...", col[-4:])
