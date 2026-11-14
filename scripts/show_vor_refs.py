"""Показывает NППРДСО строк ВОР из выгрузки pq_refresh_check (ФайлBinary.txt, UTF-16, tab).

Запуск (из venv):  python -I -X utf8 scripts/show_vor_refs.py <ФайлBinary.txt> [подстрока в наименовании]
Печатает только строки, где в наименовании есть «поз».
"""
import csv
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-16", newline="") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
print("строк:", len(rows), "| файлы:", sorted({r["ИмяФайла"][:40] for r in rows}))
n = 0
for r in rows:
    if re.search(r"поз", r["НаименованиеРабот"], re.I):
        n += 1
        print(f'{r["NПП"]:>6} | NППРДСО={r["NППРДСО"]!r:40} | ...{r["НаименованиеРабот"][-70:]!r}')
print("с «поз» в наименовании:", n)
