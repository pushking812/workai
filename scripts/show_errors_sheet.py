"""Печатает лист «Ошибки» и счётчики листов книги ВОР+СО (чтение, книга не меняется).

Запуск (из venv):  python -I -X utf8 scripts/show_errors_sheet.py <ВОР+СО.xlsx>
Связь_ВОР_СО листа не имеет (только модель): её статусы смотреть через scripts/pq_eval.ps1.
"""
import sys

import openpyxl

wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
print({ws.title: ws.max_row - 1 for ws in wb.worksheets})
for r in wb["Ошибки"].iter_rows(values_only=True):
    print(" | ".join("" if v is None else str(v)[:60] for v in r[:12]))
