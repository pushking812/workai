"""Проба: какой тип штампа получают файлы папки и что в «Наименовании документа».

Запуск: python scripts/probe_xn_types.py <папка> [...]
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from core.parsers.stamp_parser import parse_stamp  # noqa: E402

for folder in sys.argv[1:]:
    counts: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.docx"), recursive=True)):
        stamp = parse_stamp(path)
        kind = stamp.get("doc_type") or "(пусто)"
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("XN", "(пусто)"):
            print(os.path.basename(path), "|", stamp.get("doc_code"), "|", stamp.get("document_name"))
    print(folder, counts)
