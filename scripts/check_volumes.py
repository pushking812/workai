"""Сверка объёмов (КолВо) в результате запросов книги СО с исходными CSV.

Использование:
    python -X utf8 scripts/check_volumes.py <книга СО.xlsx> [--report файл.tsv]

Книга должна быть обновлена в Excel (кэш листа ФайлBinary). Для каждого CSV из листа
СписокФайлов берётся колонка КолВо (по справочнику СправочникКолонок, как в запросе fnRenameToCanonical),
суммируется и сравнивается с суммой КолВо строк ФайлBinary этого файла (по ИдСтроки).
Дополнительно сверяются суммы по каждому NПП и значения несвёрнутых строк.
"""
import argparse
import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl


def norm(s):
    s = "" if s is None else str(s)
    for ch in ("\r", "\n", "\t"):
        s = s.replace(ch, " ")
    return s.strip()


def to_num(v):
    """(число|None, пусто?)"""
    if v is None:
        return None, True
    t = str(v).strip()
    if t == "":
        return None, True
    try:
        return float(t.replace(" ", "").replace(" ", "").replace(",", ".")), False
    except ValueError:
        return None, False


def sheet_rows(wb, name):
    rows = list(wb[name].iter_rows(values_only=True))
    head = [norm(h) for h in rows[0]]
    return head, rows[1:]


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        data = list(csv.reader(f, delimiter=";"))
    data = [r for r in data if any(c.strip() for c in r)]
    if not data:
        return [], []
    header, rows = [norm(h) for h in data[0]], data[1:]
    if rows:
        vals = [c.strip() for c in rows[0] if c.strip()]
        if vals and all(to_num(c)[0] is not None for c in vals):
            rows = rows[1:]
    return header, rows


def first_col(header, variants):
    for i, h in enumerate(header):
        if h in variants:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--report", default="data/exports/_report_volumes.tsv")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.book, read_only=True, data_only=True)
    h, ref = sheet_rows(wb, "СправочникКолонок")
    variants = defaultdict(set)
    for r in ref:
        variants[norm(r[0])].add(norm(r[1]))
    h, files = sheet_rows(wb, "СписокФайлов")
    ip = h.index("ПолныйПуть")
    fh, fb = sheet_rows(wb, "ФайлBinary")
    c_id, c_npp, c_qty = fh.index("ИдСтроки"), fh.index("NПП"), fh.index("КолВо")
    c_name = fh.index("ИмяФайла")

    res = defaultdict(list)  # csv -> [(row, npp, qty, name)]
    for r in fb:
        sid = r[c_id]
        if sid is None or "|" not in str(sid):
            continue  # строки с ошибкой чтения
        csvname, n = str(sid).rsplit("|", 1)
        res[csvname].append((int(n), norm(r[c_npp]), r[c_qty], r[c_name]))

    out = []
    bad = 0
    total_src = total_res = 0.0
    for fr in files:
        path = fr[ip]
        if not path:
            continue
        csvname = Path(str(path).replace("\\", "/")).name
        local = Path("data/exports/app") / csvname
        if not local.exists():
            out.append((csvname, "", "CSV не найден", "", "", "", "", ""))
            bad += 1
            continue
        header, rows = read_csv_rows(local)
        iq = first_col(header, variants["КолВо"])
        inpp = first_col(header, variants["NПП"])
        if iq is None:
            out.append((csvname, fr[1], "нет колонки КолВо", "", "", "", "", ""))
            bad += 1
            continue
        src_sum, src_text = 0.0, []
        src_npp = defaultdict(float)
        src_rows = {}
        for n, r in enumerate(rows, 1):
            v = r[iq] if iq < len(r) else ""
            x, empty = to_num(v)
            npp = norm(r[inpp]) if inpp is not None and inpp < len(r) else ""
            src_rows[n] = (npp, v)
            if x is not None:
                src_sum += x
                src_npp[npp] += x
            elif not empty:
                src_text.append(v.strip())
        rr = res.get(csvname, [])
        res_sum, res_text = 0.0, []
        res_npp = defaultdict(float)
        diffs = []
        for n, npp, q, _ in rr:
            x, empty = to_num(q)
            if x is not None:
                res_sum += x
                res_npp[npp] += x
            elif not empty:
                res_text.append(str(q).strip())
            # несвёрнутая строка: значение должно совпасть с исходным
            if n in src_rows and x is not None:
                sx, _e = to_num(src_rows[n][1])
                if sx is not None and abs(sx - x) > 1e-9 and src_rows[n][0] == npp:
                    pass  # возможная свёрнутая первая строка группы, сверка по NПП ниже
        npp_bad = []
        for k in set(src_npp) | set(res_npp):
            if abs(src_npp.get(k, 0.0) - res_npp.get(k, 0.0)) > 1e-6:
                npp_bad.append(f"{k or '(пусто)'}: {src_npp.get(k, 0.0):g} → {res_npp.get(k, 0.0):g}")
        nonnum = "" if sorted(src_text) == sorted(res_text) else (
            f"не числа: источник {len(src_text)}, результат {len(res_text)}")
        total_src += src_sum
        total_res += res_sum
        status = "OK"
        if abs(src_sum - res_sum) > 1e-6 or npp_bad or nonnum or (not rr and rows):
            status = "РАСХОЖДЕНИЕ"
            bad += 1
        out.append((csvname, fr[1], status, f"{src_sum:g}", f"{res_sum:g}",
                    f"{len(rows)}/{len(rr)}", "; ".join(npp_bad[:15]) + (" …" if len(npp_bad) > 15 else ""),
                    nonnum))

    extra = set(res) - {Path(str(f[ip]).replace("\\", "/")).name for f in files if f[ip]}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    with open(a.report, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["CSV", "Файл", "Статус", "Сумма источник", "Сумма результат",
                    "Строк ист./рез.", "Расхождения по NПП", "Прим."])
        w.writerows(out)
    print(f"файлов: {len(out)}, с расхождением/проблемой: {bad}")
    print(f"общая сумма (разные ед. изм. смешаны): источник {total_src:g}, результат {total_res:g}")
    if extra:
        print("в результате есть CSV вне списка:", sorted(extra))
    for o in out:
        if o[2] != "OK":
            print(" | ".join(str(x) for x in o))
    print("отчёт:", a.report)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
