"""Отчёт по связям КЖ и СВОР с общей книгой ВОР+СО (Python-эталон, без Excel и PQ).

  СВОР -> ВОР:  количество «по РД» СВОР против КолВо ВОР (core/svor_link.py)
  КЖ   -> СО:   марка + сечение, метры (core/cable_link.py)
  Статусы СВОР: новая / удалена / изменена по числам, цвет из docx (core/svor.py)

Вход: книги ВОР и СО (лист ФайлBinary - то же, что читает общая книга ВОР+СО), СВОР и КЖ в docx.
Запуск (из venv):
  python -I -X utf8 scripts/make_links_report.py --vor ВОР.xlsx --so СО.xlsx [--svor СВОР.docx] [--kzh КЖ.docx] --out отчёт.xlsx
КЖ в .doc сначала конвертируется в docx (data/converted).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import openpyxl  # noqa: E402

from core import cable_link, svor_link  # noqa: E402
from core.cable_docs import project_code, read_kzh, read_so_book  # noqa: E402
from core.svor import read_svor  # noqa: E402

SVOR_COLS = ["Раздел", "Номер", "Наименование", "Ед", "П", "Р", "Откл", "Статус", "Цвет", "Замечание", "Примечание"]
LINK_COLS = ["Статус", "Режим", "Наименование", "Ед", "СВОР_Р", "ВОР", "Разница", "СтрокСВОР", "СтрокВОР"]
CABLE_COLS = ["Шифр", "Статус", "Режим", "МаркаКЖ", "Сечение", "КЖ_м", "СО_м", "Разница", "КлючСО"]


def _sheet(wb, title, cols, rows):
    ws = wb.create_sheet(title)
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    ws.freeze_panes = "A2"
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 60 if c in ("Наименование", "МаркаКЖ", "КлючСО") else 16
    return ws


def build(vor_book, so_book, svor_docx=None, kzh_docx=None):
    """Возвращает (листы, сводка): листы - {название: (колонки, строки)}."""
    sheets, summary = {}, []
    if svor_docx:
        from core.parsers.stamp_parser import parse_stamp
        svor_rows = read_svor(svor_docx)
        code = project_code(parse_stamp(svor_docx).get("doc_code"))
        vor = svor_link.read_vor_book(vor_book)
        mine = [r for r in vor if r["Шифр"] == code]
        links = svor_link.link(svor_rows, mine or vor)
        sheets["СВОР_Статусы"] = (SVOR_COLS, svor_rows)
        sheets["СВОР_ВОР"] = (LINK_COLS, links)
        cnt = {}
        for x in links:
            cnt[x["Статус"]] = cnt.get(x["Статус"], 0) + 1
        summary.append("СВОР-ВОР (шифр %s, строк ВОР %d): %s" % (code or "?", len(mine or vor), cnt))
    if kzh_docx:
        links = cable_link.link_by_project(read_kzh(kzh_docx), read_so_book(so_book))
        sheets["КЖ_СО"] = (CABLE_COLS, links)
        cnt = {}
        for x in links:
            cnt[x["Статус"]] = cnt.get(x["Статус"], 0) + 1
        summary.append("КЖ-СО: %s" % cnt)
    return sheets, summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vor", required=True)
    ap.add_argument("--so", required=True)
    ap.add_argument("--svor")
    ap.add_argument("--kzh")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not (a.svor or a.kzh):
        ap.error("нужен --svor или --kzh")
    sheets, summary = build(a.vor, a.so, a.svor, a.kzh)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, (cols, rows) in sheets.items():
        _sheet(wb, title, cols, rows)
    wb.save(a.out)
    print("\n".join(summary))
    print("Записан", a.out)


if __name__ == "__main__":
    main()
