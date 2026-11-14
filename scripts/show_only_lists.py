"""Печатает листы Только_в_ВОР и Только_в_СО книги ВОР+СО (для подбора сопоставления по наименованию).

Запуск: python -I -X utf8 scripts/show_only_lists.py <книга.xlsx>
"""
import sys

import openpyxl


def rows(ws):
    it = ws.iter_rows(values_only=True)
    head = next(it)
    for r in it:
        yield dict(zip(head, r))


def main(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    print("ЛИСТЫ", wb.sheetnames)
    print("== Только_в_ВОР")
    for r in rows(wb["Только_в_ВОР"]):
        print(r.get("NПП"), "|", r.get("NППСО"), "|", r.get("Причина"), "|", (r.get("НаименованиеРабот") or "")[:110])
    print("== Только_в_СО")
    for r in rows(wb["Только_в_СО"]):
        print(r.get("NПП"), "|", (r.get("НаименованиеИТехХар") or "")[:80], "|", (r.get("Примечание") or "")[:40])


if __name__ == "__main__":
    main(sys.argv[1])
