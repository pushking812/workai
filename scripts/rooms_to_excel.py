"""Все PDF экспликаций из «ДопФайлы/Помещения» -> один xlsx.

Листы: «Помещения» (все записи), «Проверка» (сверка итогов по документам),
«Файлы» (способ чтения, число записей, замечания), «Сверка_CSV» (если рядом с
PDF лежит ручной .pdf.csv — сравнение с результатом OCR).

Запуск (из venv):  python -I -X utf8 scripts/rooms_to_excel.py [--only текст] [--no-ocr]
Результат каждого PDF кэшируется в data/_pq_work/rooms_cache (OCR долгий),
поэтому команду можно запускать повторно: готовые файлы пропускаются.
--only ПОДСТРОКА  — обработать только файлы с этой подстрокой в имени.
--budget СЕК      — остановиться после этого времени (по умолчанию 150).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.rooms_pdf import FIELDS, parse_pdf  # noqa: E402

SRC = ROOT / "ДопФайлы" / "Помещения"
CACHE = ROOT / "data" / "_pq_work" / "rooms_cache"
OUT = ROOT / "data" / "exports" / "Помещения.xlsx"
REF = ROOT / "spravochniki.xlsx"


def _ref():
    try:
        from core.reference import load_reference
        return load_reference(REF) if REF.exists() else None
    except Exception as e:  # справочник не обязателен
        print("справочник не загружен:", e)
        return None


def _cache_path(pdf: Path) -> Path:
    return CACHE / (pdf.parent.name + "__" + pdf.stem + ".json")


def _is_vector(pdf: Path) -> bool:
    """Нет текстового слоя (буквы — контуры): нужен OCR."""
    import pdfplumber
    with pdfplumber.open(pdf) as f:
        return len(f.pages[0].chars) < 30


def process(pdf: Path, ref) -> dict:
    cp = _cache_path(pdf)
    if cp.exists() and cp.stat().st_mtime >= pdf.stat().st_mtime:
        return json.loads(cp.read_text(encoding="utf-8"))
    doc = parse_pdf(pdf, ref)
    data = {"file": doc.file, "folder": pdf.parent.name, "kind": doc.kind, "method": doc.method,
            "records": doc.records, "checks": doc.checks, "notes": doc.notes}
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


# ---------------------------------------------------------------- CSV (ручной)
def read_manual_csv(path: Path) -> list[dict]:
    """Ручной CSV: «;» разделитель, десятичная запятая заменена на «;» внутри кавычек."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    first = text.split("\n", 1)[0]
    # разделитель — тот из «;» и «,», что чаще стоит ВНЕ кавычек в первой строке
    outside = re.sub(r'"[^"]*"', "", first)
    delim = ";" if outside.count(";") >= outside.count(",") else ","
    for r in csv.reader(text.splitlines(), delimiter=delim, quotechar='"'):
        rows.append(r)
    return rows


def records_from_csv(pdf: Path, csv_path: Path, ref) -> dict:
    """Записи из ручного CSV (источник верный, OCR на сканах даёт мусор)."""
    return records_from_rows(pdf, read_manual_csv(csv_path)[1:], ref, "CSV (вручную)",
                             "записи из ручного CSV; OCR только для сверки")


def records_from_rows(pdf: Path, data_rows: list, ref, method: str, note: str) -> dict:
    """Записи из строк в формате ручного CSV (7 столбцов, без заголовка)."""
    from core.rooms_pdf import file_context, floor_code
    ctx = file_context(pdf)
    b = ctx["building"]
    base = {k: "" for k in FIELDS}
    base.update({"Здание_код": b, "Этаж_код": floor_code(b, ctx), "Этаж_файл": ctx["floor_label"],
                 "Лист": ctx["sheet"], "Файл": pdf.name, "Чтение": method, "Тип_экспликации": 1})
    notes = []
    if ref is not None and b:
        from core.reference import ground_state
        base["Здание"] = ref.building_name(b)
        base["Наземный_подземный"] = ground_state(ref, b, base["Этаж_код"])
    recs = []
    for r in (x + [""] * 7 for x in data_rows):
        if not r[1].strip():
            continue
        fl, pr = _num(r[4]), _num(r[3])
        flags = []
        if r[4].strip() not in ("", "-") and fl is None:
            flags.append("площадь не число")
        recs.append({**base, "Номер_помещения": r[1].strip(), "Номер_правоуст": r[0].strip(),
                     "Назначение": r[2].strip(), "Площадь_м2": fl, "Площадь_правоуст_м2": pr,
                     "Подразделение": r[5].strip(), "Примечание": r[6].strip(), "Проверить": ", ".join(flags)})
    notes.append(note)
    return {"file": pdf.name, "folder": pdf.parent.name, "kind": 1, "method": method.split(" ")[0], "records": recs,
            "checks": [], "notes": notes}


def _num(s):
    t = re.sub(r"\s+", "", str(s or "")).replace(";", ".").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def compare_manual(data: dict, csv_path: Path, label: str = "OCR") -> list[dict]:
    """Сверка записей OCR с ручным CSV по внутреннему номеру помещения."""
    return compare_rows(data, read_manual_csv(csv_path)[1:], label)


def compare_rows(data: dict, manual_rows: list, label: str = "OCR") -> list[dict]:
    """Сверка записей `data` с эталонными строками (формат ручного CSV, без заголовка)."""
    def keyed(items):          # один номер может повторяться: пары по порядку
        seen, out_ = {}, {}
        for num, item in items:
            n = seen.get(num, 0)
            seen[num] = n + 1
            out_[num if n == 0 else f"{num} (#{n + 1})"] = item
        return out_

    manual = keyed((r[1].strip(), r) for r in ([x + [""] * 7 for x in manual_rows])
                   if r[1].strip())
    ocr = keyed((str(rec["Номер_помещения"]).strip(), rec) for rec in data["records"])
    out = []
    for k in sorted(set(manual) | set(ocr), key=lambda x: (len(x), x)):
        m, o = manual.get(k), ocr.get(k)
        if m is None:
            out.append({"Файл": data["file"], "Номер": k, "Поле": "помещение", "CSV": "", "OCR": f"есть только в {label}"})
            continue
        if o is None:
            out.append({"Файл": data["file"], "Номер": k, "Поле": "помещение", "CSV": "есть", "OCR": f"нет в {label}"})
            continue
        pairs = [("Номер_правоуст", m[0], o["Номер_правоуст"], "s"),
                 ("Назначение", m[2], o["Назначение"], "s"),
                 ("Площадь_правоуст_м2", m[3], o["Площадь_правоуст_м2"], "n"),
                 ("Площадь_м2", m[4], o["Площадь_м2"], "n"),
                 ("Подразделение", m[5], o["Подразделение"], "s"),
                 ("Примечание", m[6], o["Примечание"], "s")]
        for name, a, b, t in pairs:
            if t == "n":
                na, nb = _num(a), (b if isinstance(b, (int, float)) else _num(b))
                same = (na is None and nb is None) or (na is not None and nb is not None and abs(na - nb) < 0.005)
            else:
                same = re.sub(r"\W", "", str(a).lower()) == re.sub(r"\W", "", str(b).lower())
            if not same:
                out.append({"Файл": data["file"], "Номер": k, "Поле": name, "CSV": a, "OCR": b})
    return out


# --------------------------------------------------------------------- xlsx
def write_xlsx(results: list[dict], diffs: list[dict], path: Path, diffs_ai: list[dict] | None = None) -> None:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    def sheet(ws, headers, rows):
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="DDEBF7")
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, h in enumerate(headers, 1):
            w = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:300]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 8), 60)

    ws = wb.active
    ws.title = "Помещения"
    rows = [[rec.get(k, "") for k in FIELDS] for d in results for rec in d["records"]]
    sheet(ws, FIELDS, rows)
    sheet(wb.create_sheet("Проверка"), ["Файл", "Итого", "Совпало", "Детали"],
          [[d["file"], c["Итого"], c["Совпало"], c["Детали"]] for d in results for c in d["checks"]])
    sheet(wb.create_sheet("Файлы"), ["Папка", "Файл", "Тип", "Чтение", "Записей", "Итогов не сошлось", "Замечания"],
          [[d["folder"], d["file"], d["kind"], d["method"], len(d["records"]),
            sum(1 for c in d["checks"] if c["Совпало"] != "да"), "; ".join(d["notes"])] for d in results])
    if diffs:
        sheet(wb.create_sheet("Сверка_CSV"), ["Файл", "Номер", "Поле", "CSV", "OCR"],
              [[d["Файл"], d["Номер"], d["Поле"], d["CSV"], d["OCR"]] for d in diffs])
    if diffs_ai:
        sheet(wb.create_sheet("Сверка_AI"), ["Файл", "Номер", "Поле", "CSV", "AI"],
              [[d["Файл"], d["Номер"], d["Поле"], d["CSV"], d["OCR"]] for d in diffs_ai])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def ai_rows(pdf: Path, settings: dict, ask=None) -> list:
    """Строки таблицы от модели (кэш: rooms_cache/<имя>.ai.csv — сырой ответ модели)."""
    from core import ai_client, rooms_ai
    cp = _cache_path(pdf).with_suffix(".ai.csv")
    if cp.exists() and cp.stat().st_mtime >= pdf.stat().st_mtime:
        return rooms_ai.parse_csv_text(cp.read_text(encoding="utf-8"))
    text = (ask or ai_client.ask)(rooms_ai.PROMPT, settings=settings, system=rooms_ai.SYSTEM,
                                  files=[ai_client.file_part(pdf)])
    rows = rooms_ai.parse_csv_text(text)       # ошибка модели -> AIError, в кэш не пишем
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(ai_client.strip_fences(text), encoding="utf-8")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--budget", type=float, default=150.0)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--ocr_with_ai", action="store_true",
                    help="файлы без текстового слоя отдать AI-модели (ответ — сырой CSV); "
                         "если есть ручной CSV — только сверка. Нужен ASK_API_KEY или ai_api_key в настройках")
    a = ap.parse_args()

    settings = {}
    if a.ocr_with_ai:
        from core import ai_client, config
        settings = config.load_config()
        if not ai_client.get_key(settings):
            print("нет ключа: задайте ASK_API_KEY или ai_api_key в настройках")
            return 2

    ref = _ref()
    pdfs = sorted(SRC.rglob("*.pdf"))
    if a.only:
        pdfs = [p for p in pdfs if a.only.lower() in p.name.lower()]
    pdfs.sort(key=lambda p: (not _cache_path(p).exists(), _is_vector(p), str(p)))  # готовые, потом текстовые, потом OCR
    t0 = time.time()
    results, pending, diffs, diffs_ai = [], [], [], []
    for p in pdfs:
        csv_path = p.with_name(p.name + ".csv")
        ai_done = None
        if a.ocr_with_ai and _is_vector(p):
            try:
                rows = ai_rows(p, settings)
                has_csv = csv_path.exists()   # спорные строки проверены человеком: AI верен
                ai_done = records_from_rows(
                    p, rows, ref, "AI (проверено)" if has_csv else "AI (проверить)",
                    "распознано моделью; спорные строки сверены со сканом, ручной CSV — только для сверки"
                    if has_csv else "распознано моделью, требует проверки")
                print(f"{p.name}: AI, записей {len(ai_done['records'])}")
            except Exception as e:       # AIError и сеть: этот файл идёт обычным путём
                print("AI не смог", p.name, "-", e)
        if ai_done and csv_path.exists():
            diffs_ai += compare_rows(ai_done, read_manual_csv(csv_path)[1:], "AI")
        if ai_done:
            results.append(ai_done)
            continue
        if csv_path.exists():
            d = records_from_csv(p, csv_path, ref)
            results.append(d)
            if _cache_path(p).exists():      # OCR только из кэша, для сверки
                diffs += compare_manual(json.loads(_cache_path(p).read_text(encoding="utf-8")), csv_path)
            print(f"{p.name}: CSV, записей {len(d['records'])}")
            continue
        if ai_done:
            results.append(ai_done)
            continue
        cached = _cache_path(p).exists()
        if time.time() - t0 > a.budget and not cached:
            pending.append(p.name)
            continue
        try:
            d = process(p, ref)
        except Exception as e:
            print("ОШИБКА", p.name, e)
            d = {"file": p.name, "folder": p.parent.name, "kind": 0, "method": "", "records": [],
                 "checks": [], "notes": [f"ошибка: {e}"]}
        results.append(d)
        print(f"{p.name}: тип {d['kind']}, {d['method']}, записей {len(d['records'])}, "
              f"итогов не сошлось {sum(1 for c in d['checks'] if c['Совпало'] != 'да')}")
    if pending:
        print("не успели (запустите ещё раз):", *pending, sep="\n  ")
    write_xlsx(results, diffs, Path(a.out), diffs_ai)
    print(f"записано: {a.out}; файлов {len(results)} из {len(pdfs)}, записей "
          f"{sum(len(d['records']) for d in results)}, расхождений OCR с CSV {len(diffs)}"
          + (f", AI с CSV {len(diffs_ai)}" if a.ocr_with_ai else ""))
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
