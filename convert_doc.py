"""Конвертация .doc -> .docx через Word COM, разбор штампа и запись в xlsx.

Запуск: python convert_doc.py КЖ [другая_папка ...]
Для каждой папки: .doc конвертируются в _conv/<папка>/NN/<имя>.docx (оригиналы не трогаются),
.docx разбираются как есть, результат пишется на лист с именем папки в vor_parsing_results.xlsx.
"""
import glob
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
import openpyxl
import win32com.client

from core.parsers.stamp_parser import parse_stamp
from tests.test_stamp_parser import EXCEL_CELL_LIMIT, RESULT_FIELDS, RESULTS_PATH

WD_FORMAT_DOCX = 16
REQUIRED = ("doc_code", "revision", "revision_date", "stage", "organization", "title", "document_name")
OUT_ROOT = os.path.abspath("_conv")


def convert_and_parse(word, folder):
    out = os.path.join(OUT_ROOT, folder)
    files = sorted(glob.glob(os.path.join(folder, "*.doc")) + glob.glob(os.path.join(folder, "*.docx")))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    rows, ok, bad = [], 0, 0
    for i, f in enumerate(files):
        name = os.path.basename(f)
        path = os.path.abspath(f)
        if f.lower().endswith(".doc"):
            sub = os.path.join(out, "%02d" % i)
            os.makedirs(sub, exist_ok=True)
            dst = os.path.join(sub, os.path.splitext(name)[0] + ".docx")
            try:
                d = word.Documents.Open(path, ReadOnly=True, AddToRecentFiles=False)
                d.SaveAs2(dst, FileFormat=WD_FORMAT_DOCX)
                d.Close(False)
            except Exception as e:
                bad += 1
                print("CONVERT-ERROR", name, str(e)[:100])
                continue
        else:
            dst = path
        try:
            r = parse_stamp(dst)
        except Exception as e:
            bad += 1
            print("ERROR", name, type(e).__name__, str(e)[:100])
            continue
        ok += 1
        rows.append((name, r))
        miss = [k for k in REQUIRED if not r.get(k)]
        print("OK  ", name[:50].ljust(50), r.get("stamp_profile"), "rev", r.get("revision"), r.get("revision_date"),
              "л", r.get("sheet"), "/", r.get("sheets_total"), "исп", len(r.get("executors") or []),
              "пусто:", ",".join(miss) or "-")
        for d in r.get("discrepancies") or []:
            print("      РАСХОЖДЕНИЕ", d["message"])
    print("ok", ok, "errors", bad, "total", len(files))
    return rows


def write_sheet(wb, title, rows):
    title = title[:31]
    if title in wb.sheetnames:
        del wb[title]
    ws = wb.create_sheet(title)
    ws.append(["file", *RESULT_FIELDS])
    for name, r in rows:
        row = [name]
        for field in RESULT_FIELDS:
            v = r.get(field)
            if field == "executors":
                v = "; ".join(", ".join(i[k] for k in ("position", "name", "signature", "date")) for i in v or [])
            elif field == "filename_dates":
                v = ", ".join(v or [])
            elif field == "discrepancies":
                v = "; ".join(i["message"] for i in v or [])
            if isinstance(v, str) and len(v) > EXCEL_CELL_LIMIT:
                v = v[:EXCEL_CELL_LIMIT]
            row.append(v)
        ws.append(row)


def main(folders):
    if not folders:
        print(__doc__)
        return
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    results = {}
    try:
        for folder in folders:
            print("==", folder)
            results[folder] = convert_and_parse(word, folder)
    finally:
        word.Quit()
    wb = openpyxl.load_workbook(RESULTS_PATH) if os.path.exists(RESULTS_PATH) else openpyxl.Workbook()
    for folder, rows in results.items():
        write_sheet(wb, os.path.basename(os.path.normpath(folder)), rows)
        print("xlsx: лист", folder, len(rows), "строк")
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        del wb["Sheet"]
    wb.save(RESULTS_PATH)


if __name__ == "__main__":
    main(sys.argv[1:])
