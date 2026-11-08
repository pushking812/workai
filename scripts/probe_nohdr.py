"""Сводка заголовков таблиц docx в папке: сколько раз встречается каждый и таблицы без шапки."""
import glob
import sys
from collections import Counter

from core.parsers.docx_parser import extract_tables_from_docx
from core.parsers.header_profiles import parse_table

root = sys.argv[1] if len(sys.argv) > 1 else "ВОР"
files = glob.glob(root + "/**/*.docx", recursive=True)
counter: Counter = Counter()
no_header = 0
for path in files:
    for table in extract_tables_from_docx(path):
        if not table:
            continue
        headers = parse_table(table).headers
        if not any(headers):
            no_header += 1
        counter.update(h for h in headers if h)
print(len(files), "files; tables without header:", no_header)
for header, count in counter.most_common(40):
    print(count, header[:90])
