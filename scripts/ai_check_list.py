"""Список спорных строк «ваш CSV против AI» для ручной проверки по PDF.

Читает лист Сверка_AI из data/exports/Помещения_AI.xlsx, пишет
data/exports/Помещения_AI_проверить.xlsx: приоритет, файл, помещение, поля,
значения CSV и AI, пустые столбцы «верно» и «комментарий».
Приоритет 1: строка есть только в одном источнике или разные числа (площадь);
2: номер правоустанавливающего документа; 3: текст (назначение, примечание).
Запуск: python -I -X utf8 scripts/ai_check_list.py [входной.xlsx] [выходной.xlsx]
"""
import sys
from collections import OrderedDict

import openpyxl

SRC = "data/exports/Помещения_AI.xlsx"
DST = "data/exports/Помещения_AI_проверить.xlsx"
PRIO = {"помещение": 1, "Площадь_м2": 1, "Площадь_правоуст_м2": 1,
        "Номер_правоуст": 2}


def build(rows):
    """rows: (Файл, Номер, Поле, CSV, AI) -> список строк для проверки."""
    groups = OrderedDict()
    for f, num, field, csv_v, ai_v in rows:
        g = groups.setdefault((f, num), {"prio": 3, "items": []})
        g["prio"] = min(g["prio"], PRIO.get(field, 3))
        g["items"].append((field, csv_v, ai_v))
    out = []
    for (f, num), g in groups.items():
        out.append((g["prio"], f, num,
                    "; ".join(i[0] for i in g["items"]),
                    "; ".join(str(i[1]) for i in g["items"]),
                    "; ".join(str(i[2]) for i in g["items"])))
    out.sort(key=lambda r: (r[0], r[1]))
    return out


def main(src=SRC, dst=DST):
    wb = openpyxl.load_workbook(src, read_only=True)
    rows = [r[:5] for r in list(wb["Сверка_AI"].iter_rows(values_only=True))[1:]
            if r and r[0]]
    res = build(rows)
    out = openpyxl.Workbook()
    ws = out.active
    ws.title = "Проверить"
    ws.append(["Приоритет", "Файл", "Помещение", "Поля", "CSV", "AI",
               "Верно (CSV/AI)", "Комментарий"])
    for r in res:
        ws.append(list(r) + ["", ""])
    out.save(dst)
    print(f"записано: {dst}; помещений {len(res)}, расхождений {len(rows)}")
    return res


if __name__ == "__main__":
    main(*sys.argv[1:3])
