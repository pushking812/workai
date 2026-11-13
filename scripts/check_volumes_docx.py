"""Сверка объёмов (Кол-во) исходных таблиц Word (data/converted/*.docx) с выгруженными CSV.

Использование:
    python -X utf8 scripts/check_volumes_docx.py <книга СО.xlsx> [--report файл.tsv]

Список файлов и CSV берётся из листа СписокФайлов книги. Для каждой таблицы документа
колонка количества определяется по тексту шапки («кол-во», «количество»), значения
суммируются напрямую из ячеек Word, затем сравниваются с суммой КолВо в CSV этой таблицы.
Таблицы, которые не выгружены в CSV (другая шапка, чем у первой), попадают в отчёт отдельно.
"""
import argparse
import csv
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.doc_converter import read_doc_stamp_source  # noqa: E402
from core.parsers.docx_parser import extract_headers, extract_tables_from_docx  # noqa: E402
from scripts.check_volumes import first_col, norm, read_csv_rows, sheet_rows, to_num  # noqa: E402

TABLE_NO = re.compile(r"_table_(\d+)\.csv$", re.IGNORECASE)
QTY = ("колво", "количество")


def squash(s):
    return re.sub(r"[\s\-]+", "", norm(s)).lower()


def qty_col(table, data_start):
    for row in table[:data_start]:
        for j, cell in enumerate(row):
            t = squash(cell)
            if any(k in t for k in QTY):
                return j
    return None


def col_sum(table, col, start):
    total, text = 0.0, []
    for row in table[start:]:
        if col >= len(row):
            continue
        x, empty = to_num(row[col])
        if x is not None:
            total += x
        elif not empty:
            text.append(str(row[col]).strip())
    return total, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--report", default="data/exports/_report_volumes_docx.tsv")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.book, read_only=True, data_only=True)
    h, ref = sheet_rows(wb, "СправочникКолонок")
    variants = defaultdict(set)
    for r in ref:
        variants[norm(r[0])].add(norm(r[1]))
    h, files = sheet_rows(wb, "СписокФайлов")
    ip, iname = h.index("ПолныйПуть"), h.index("ИмяФайла")

    # Документ определяется по хэшу из имени CSV (в БД files.hash), а не по имени файла:
    # в папках ИЗМ0/ИЗМ1 имена документов повторяются.
    db = sqlite3.connect("data/app.db")
    paths = {}
    for h_, p_ in db.execute("select hash, path from files"):
        paths.setdefault(h_[:16], p_)

    docs = defaultdict(dict)  # путь исходного документа -> {N таблицы: csv}
    for r in files:
        if not r[ip]:
            continue
        csvname = Path(str(r[ip]).replace("\\", "/")).name
        m = TABLE_NO.search(csvname)
        src = paths.get(csvname.split("_")[0], "?" + str(r[iname]))
        docs[src][int(m.group(1)) if m else 1] = csvname

    out, bad = [], 0
    tot_raw = tot_csv = 0.0
    for src, csvs in sorted(docs.items()):
        name = Path(src.lstrip("?")).name
        if src.startswith("?") or not Path(src).exists():
            out.append((name, "", "исходный файл не найден в БД/на диске", "", "", ""))
            bad += 1
            continue
        try:
            docx = Path(read_doc_stamp_source(src, "data/converted"))
        except OSError as exc:
            out.append((name, "", f"не открыть файл: {exc}", "", "", ""))
            bad += 1
            continue
        if docx.suffix.lower() != ".docx":
            out.append((name, "", "нет конвертированного .docx (Word недоступен)", "", "", ""))
            bad += 1
            continue
        try:
            tables = extract_tables_from_docx(str(docx))
        except Exception as exc:  # noqa: BLE001
            out.append((name, "", f"ошибка чтения .docx: {exc}", "", "", ""))
            bad += 1
            continue
        first_col_idx, first_width = None, None
        for n, tbl in enumerate(tables, 1):
            if not tbl:
                continue
            _h, ds = extract_headers(tbl)
            col = qty_col(tbl, ds)
            if col is not None and first_col_idx is None:
                first_col_idx, first_width = col, max(len(r) for r in tbl)
            note = ""
            if col is None:
                # продолжение без шапки: колонка как в первой таблице с тем же числом колонок
                if first_col_idx is not None and max(len(r) for r in tbl) >= first_width and n in csvs:
                    col, ds, note = first_col_idx, 0, "продолжение без шапки"
                else:
                    if n in csvs:
                        # выгруженная таблица, в которой колонка количества не определилась
                        out.append((name, f"таблица {n}", "КОЛОНКА КОЛ-ВО В WORD НЕ НАЙДЕНА", "", "", csvs[n]))
                        bad += 1
                    continue  # иначе не спецификация (штамп, обложка и т. п.)
            raw_sum, raw_text = col_sum(tbl, col, ds)
            csvname = csvs.get(n)
            if csvname is None:
                if raw_sum or raw_text:
                    out.append((name, f"таблица {n}", "НЕ ВЫГРУЖЕНА", f"{raw_sum:g}", "", f"не числа: {len(raw_text)}"))
                    bad += 1
                continue
            header, rows = read_csv_rows(Path("data/exports/app") / csvname)
            iq = first_col(header, variants["КолВо"])
            if iq is None:
                iq_note = "в CSV нет колонки КолВо"
                csv_sum, csv_text = 0.0, []
            else:
                iq_note = ""
                csv_sum, csv_text = col_sum(rows, iq, 0)
            tot_raw += raw_sum
            tot_csv += csv_sum
            ok = abs(raw_sum - csv_sum) <= 1e-6 and len(raw_text) == len(csv_text) and not iq_note
            if not ok:
                bad += 1
            extra = "; ".join(x for x in (note, iq_note,
                              "" if len(raw_text) == len(csv_text) else
                              f"не числа: Word {len(raw_text)}, CSV {len(csv_text)}") if x)
            out.append((name, f"таблица {n}", "OK" if ok else "РАСХОЖДЕНИЕ",
                        f"{raw_sum:g}", f"{csv_sum:g}", extra))

    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    with open(a.report, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["Документ", "Таблица", "Статус", "Сумма Word", "Сумма CSV", "Прим."])
        w.writerows(out)
    print(f"строк отчёта: {len(out)}, проблем: {bad}")
    print(f"сумма Word {tot_raw:g}, сумма CSV {tot_csv:g}")
    for o in out:
        if o[2] != "OK":
            print(" | ".join(str(x) for x in o))
    print("отчёт:", a.report)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
