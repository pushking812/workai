"""Оформляет _report_reconcile_totals.tsv в Excel.

Запуск (venv, -I -X utf8): python reconcile_to_xlsx.py [отчёт.tsv] [книга.xlsx]
"""
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

src = sys.argv[1] if len(sys.argv) > 1 else "data/exports/_report_reconcile_totals.tsv"
dst = sys.argv[2] if len(sys.argv) > 2 else "data/exports/Сверка_итогов_СОУЭ1.xlsx"

sections = []  # (title, rows)
for line in open(src, encoding="utf-8-sig").read().splitlines():
    if line.startswith("== "):
        sections.append((line[3:], []))
    elif sections and line.strip():
        sections[-1][1].append(line.split("\t"))
    elif not sections:
        continue
tail = [l for l in open(src, encoding="utf-8-sig").read().splitlines() if l.startswith("остаток")]


def conv(v):
    if v in ("None", ""):
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return v


HEAD = PatternFill("solid", fgColor="1F4E78")
SUB = PatternFill("solid", fgColor="DDEBF7")
bold = Font(bold=True)
white = Font(bold=True, color="FFFFFF")


def put_table(ws, r0, header, rows):
    for j, h in enumerate(header, 1):
        c = ws.cell(r0, j, h)
        c.font, c.fill = white, HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, row in enumerate(rows, r0 + 1):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, conv(v))
    return r0 + len(rows) + 1


def widths(ws, mx=60):
    for col in ws.columns:
        n = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(n + 2, 9), mx)


wb = Workbook()
ws = wb.active
ws.title = "Итоги"
label = sys.argv[3] if len(sys.argv) > 3 else "СОУЭ 1 этап"
auto = len(sys.argv) > 4 and sys.argv[4] == "auto"
ws["A1"] = f"Сверка итогов комплекта {label}: ведомость (ВОР), спецификация (СО), сводная"
ws["A1"].font = Font(bold=True, size=13)

by = {t.split(":")[0].split(" (")[0].strip(): rows for t, rows in sections}
tot = by["ИТОГО"]
r = 3
ws.cell(r, 1, "Общие итоги (разные единицы сложены, только ориентир)").font = bold
r += 1
r = put_table(ws, r, ["Показатель", "Значение", "", "Строк"],
              [[tot[0][0], tot[0][1], "", tot[0][3]],
               [tot[1][0], tot[1][1], "", ""],
               [tot[2][0], tot[2][1], "", tot[2][3]],
               [tot[3][0], tot[3][1], "", ""]])
r += 1
ws.cell(r, 1, "По единицам измерения").font = bold
r += 1
u = by["ПО ЕДИНИЦАМ"]
r = put_table(ws, r, u[0], u[1:])
r += 1
ws.cell(r, 1, "Куда девается разница").font = bold
r += 1
expl = [
    ["ВОР → сводная", "Разница 198 = 4 строки листа «Только_в_ВОР»: 7.1 (27 шт, пункта нет в СО), 19.1 (169 шт), 1.9 (1 шт), 28 (1 система). Ссылки на СО нет."],
    ["СО → сводная", "Разница 6468 = 31 строка листа «Только_в_СО», на них не ссылается ни одна строка ВОР: крепёж и расходники (6213 шт и 80 уп), оборудование без строки ВОР (поз. 29–37, 42–44), хомуты 35 к-т (поз. 25), КМО 4 шт (14.13)."],
    ["Метры", "Совпадают полностью: ВОР 7782, СО 7782."],
    ["Штуки: СО больше на 5237", "Строка ВОР в метрах (кабель-канал, лоток, труба) связана с десятками строк СО (угол, скоба, дюбель, саморез). Объём ВОР учтён один раз, у остальных строк СО он 0, а штуки СО учтены полностью."],
    ["Штуки: ВОР 511 против СО 54 (разница 457)", "Заделка проходок: в ВОР проходки (169 шт), в СО упаковки материала (герметик, плита, лента), плюс КМО 4 шт. Разные величины."],
    ["Пункт 22, нарезка 169 шт", "В СО нет штучной строки, единицы разные, в сводной СО пусто."],
    ["Кабель 1x2x1,5, 33 м", "Ссылка ВОР сдвинута: ВОР 14.12 ссылается на СО 14.11 (кабель 1,78, 10 м), ВОР 14.13 (КМО) на СО 14.12 (кабель 1,5, 33 м). Правильные пары по наименованию: 14.12→14.12, 14.13→14.13. Поэтому 4 шт КМО в «Только_в_СО», а 33 м кабеля без СО."],
]
if auto and by.get("ПОЯСНЕНИЯ"):
    expl = [x[:2] for x in by["ПОЯСНЕНИЯ"][1:] if not x[0].startswith("остаток")]
elif auto:
    expl = [
        ["ВОР → сводная", "Разница = строки листа «Только_в_ВОР» (у них нет пары в СО)."],
        ["СО → сводная", "Разница = строки листа «Только_в_СО» (на них не ссылается ни одна строка ВОР)."],
        ["Остальное", "См. листы «Расхождения_сводной» и «Виды_расхождений». Текстовые пояснения по причинам для этого комплекта не формируются автоматически."],
    ]
r = put_table(ws, r, ["Что", "Объяснение"], expl)
r += 1
for t in tail:
    p = t.split("\t")
    ws.cell(r, 1, p[0]).font = bold
    ws.cell(r, 2, conv(p[1]))
    r += 1
ws.column_dimensions["A"].width = 42
ws.column_dimensions["B"].width = 100
for c in "CDEFGHI":
    ws.column_dimensions[c].width = 14
for row in ws.iter_rows(min_row=1):
    for c in row:
        if isinstance(c.value, str) and len(c.value) > 60:
            c.alignment = Alignment(wrap_text=True, vertical="top")

names = {"Только_в_СО": "Только_в_СО", "Только_в_ВОР": "Только_в_ВОР",
         "Сводная: строки, где СуммаВОР не равна СуммаСО": "Расхождения_сводной",
         "Сводная: разница СуммаВОР - СуммаСО по видам строк и единицам": "Виды_расхождений"}
for title, rows in sections:
    key = next((v for k, v in names.items() if title.startswith(k)), None)
    if not key or not rows:
        continue
    w = wb.create_sheet(key)
    w["A1"] = title
    w["A1"].font = bold
    put_table(w, 3, rows[0], [x for x in rows[1:] if not x[0].startswith("остаток")])
    w.freeze_panes = "A4"
    w.auto_filter.ref = f"A3:{get_column_letter(len(rows[0]))}{len(rows) + 2}"
    widths(w)

wb.save(dst)
print("saved", dst)

