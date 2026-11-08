"""Где в таблицах docx номер строки записан со скобкой (`18)`) и какие таблицы без шапки."""
import glob
import re
import sys

from core.parsers.docx_parser import extract_tables_from_docx
from core.parsers.header_profiles import parse_table

root = sys.argv[1] if len(sys.argv) > 1 else "ВОР"
pattern = re.compile(r"^\s*\d+\)\s*$")
for path in sorted(glob.glob(root + "/**/*.docx", recursive=True)):
    for index, table in enumerate(extract_tables_from_docx(path), start=1):
        if not table:
            continue
        hits = [
            str(row[0]).strip()
            for row in table
            if row and pattern.match(str(row[0]))
        ]
        if hits:
            no_header = not any(parse_table(table).headers)
            print(f"{path} | таблица {index} | без шапки: {no_header} | "
                  f"номера: {', '.join(hits[:5])}{'...' if len(hits) > 5 else ''} ({len(hits)})")
