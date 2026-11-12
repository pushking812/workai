"""Проба: нумерация через стили абзацев (pStyle -> styles.xml -> numPr).

Запуск: python scripts/probe_style_numbering.py <файл.docx>
"""
from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter


def main(path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    z = zipfile.ZipFile(path)
    styles = z.read("word/styles.xml").decode("utf8")
    doc = z.read("word/document.xml").decode("utf8")
    found = []
    for m in re.finditer(r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', styles, re.S):
        n = re.search(r"<w:numPr>(.*?)</w:numPr>", m.group(2), re.S)
        if n:
            found.append((m.group(1), n.group(1)))
    print("styles with numPr:", found)
    print("pStyle usage:", Counter(re.findall(r'<w:pStyle w:val="([^"]+)"', doc)).most_common(10))
    tbl = doc.find("<w:tbl>")
    rows = re.findall(r"<w:tr[ >].*?</w:tr>", doc[tbl:], re.S)
    print("rows:", len(rows))
    for r in rows[3:6]:
        print("ROW:", r[:1500])
        print()


if __name__ == "__main__":
    main(sys.argv[1])
