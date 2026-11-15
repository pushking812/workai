import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import make_links_report as mlr  # noqa: E402


def _book(path, header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ФайлBinary"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_cable_sheet_from_books_and_docx_free(tmp_path, monkeypatch):
    so = tmp_path / "so.xlsx"
    _book(so, ["ИдСтроки", "NПП", "НаименованиеИТехХар", "ТипМаркаОбозначение", "ЕдИзм", "КолВо", "ШифрПроекта"],
          [["1", "1", "Кабель телефонный", "ТППнг(А)-HF 20х2х0,64", "м", 105, "А-СДС"]])
    monkeypatch.setattr(mlr, "read_kzh", lambda p: [{"Марка": "ТППнг(А)-HF", "Сечение": "20х2х0,64", "Длина": "105", "Шифр": "А-СДС"}])
    sheets, summary = mlr.build(str(tmp_path / "vor.xlsx"), str(so), kzh_docx="x.docx")
    cols, rows = sheets["КЖ_СО"]
    assert rows[0]["Статус"] == "совпало" and rows[0]["Шифр"] == "А-СДС"
    assert "совпало" in summary[0]


def test_main_writes_workbook(tmp_path, monkeypatch):
    so, out = tmp_path / "so.xlsx", tmp_path / "r.xlsx"
    _book(so, ["ИдСтроки", "NПП", "НаименованиеИТехХар", "ТипМаркаОбозначение", "ЕдИзм", "КолВо", "ШифрПроекта"], [])
    monkeypatch.setattr(mlr, "read_kzh", lambda p: [{"Марка": "К", "Сечение": "2х1", "Длина": "5", "Шифр": ""}])
    mlr.main(["--vor", "v.xlsx", "--so", str(so), "--kzh", "k.docx", "--out", str(out)])
    ws = openpyxl.load_workbook(out)["КЖ_СО"]
    assert [c.value for c in ws[1]][:3] == ["Шифр", "Статус", "Режим"]
    assert ws.cell(2, 2).value == "только в КЖ"


def test_real_sds_full_report(tmp_path):
    kzh = ROOT / "data" / "converted" / "45. КЖ - 2 этап - СДС.docx"
    books = ROOT / "data" / "_pq_work" / "sds_new" / "books"
    svor_dir = ROOT / "РД" / "ЕСТ-ПМ-80825-Р-2-СДС" / "ИЗМ1 - согласован"
    svor = next(iter(svor_dir.rglob("*СВОР*.docx")), None) if svor_dir.exists() else None
    vor = next(iter(books.glob("ВОР_*.xlsx")), None) if books.exists() else None
    so = next(iter(books.glob("СО_*.xlsx")), None) if books.exists() else None
    if not (kzh.exists() and svor and vor and so):
        pytest.skip("нет файлов комплекта СДС")
    out = tmp_path / "r.xlsx"
    mlr.main(["--vor", str(vor), "--so", str(so), "--svor", str(svor), "--kzh", str(kzh), "--out", str(out)])
    wb = openpyxl.load_workbook(out)
    assert set(wb.sheetnames) == {"СВОР_Статусы", "СВОР_ВОР", "КЖ_СО"}
    stat = [r[0].value for r in wb["СВОР_ВОР"].iter_rows(min_row=2)]
    assert stat.count("совпало") >= 100
