"""Шаблон СО: роли, написания шапок, одна книга на тип, запросы без ВОР-специфики."""

from __future__ import annotations

import glob
import os

import openpyxl
import pytest

from core import database, query_builder

TEMPLATE = query_builder.TEMPLATES["СО"]["path"]
VOR_TEMPLATE = query_builder.TEMPLATES["ВОР"]["path"]
pytestmark = pytest.mark.skipif(
    not (os.path.isfile(TEMPLATE) and os.path.isfile(VOR_TEMPLATE)), reason="нет шаблонов")

# Шапки СО так, как они лежат в CSV (разные оформления спецификаций)
HEADERS_A = ["Поз.", "Наименование и техническая характеристика",
             "Тип, марка, обозначение документа, опросного листа", "Код продукции", "Поставщик",
             "Ед. изме- ре- ния", "Коли- чест- во", "Масса 1 ед., кг", "Приме- чание"]
HEADERS_B = ["№ п/п", "Наименование и техническая характеристика",
             "Тип, марка, обозначение документа, опросного листа",
             "Код оборудования, изделия, материала", "Завод-изготовитель", "Единица измерения",
             "Кол-во", "Масса единицы, кг", "Примечание"]


def _add(db, tmp_path, rel, doc_type, headers):
    connection = database.init_db(db)
    try:
        file_id = database.add_file(
            connection, "h_" + rel.replace("/", "_"), str(tmp_path / rel), os.path.basename(rel),
            {"doc_code": "ЕСТ-ПМ-80825-Р-1-АПС." + doc_type, "doc_type": doc_type, "revision": "0",
             "revision_date": "2026-09-17", "stamp_date": "2026-09-17",
             "revision_date_source": "stamp", "stamp_status": "OK"},
        )
        csv = tmp_path / f"h_{file_id}_table_1.csv"
        csv.write_text(";".join(headers) + "\n" + ";".join("1" for _ in headers) + "\n", encoding="utf-8-sig")
        connection.execute("UPDATE files SET csv_path = ? WHERE id = ?", (str(csv), file_id))
        connection.commit()
        return file_id
    finally:
        connection.close()


def test_template_roles_and_sheet():
    spec = query_builder.TEMPLATES["СО"]
    roles = query_builder._template_roles(spec)
    assert roles == ["NПП", "НаименованиеИТехХар", "ТипМаркаОбозначение", "КодПродукции", "Поставщик",
                     "ЕдИзм", "КолВо", "Масса1ЕдКг", "Примечание"]
    wb = openpyxl.load_workbook(TEMPLATE)
    assert "СписокСО" in wb.sheetnames and "СписокВОР" not in wb.sheetnames
    assert "СписокСО" in wb["СписокСО"].tables


def test_so_queries_have_no_vor_specific_steps():
    code = ""
    for path in glob.glob(os.path.join("PQ", "СО", "запросы", "*.pq")):
        with open(path, encoding="utf-8-sig") as handle:
            code += handle.read()
    for forbidden in ("fnParseChertezhi", "fnParseSpec", "fnSplitReferences", "NППРДСО", "ЛистыРД",
                      "СписокВОР"):
        assert forbidden not in code, forbidden
    assert "СписокСО" in code and "КлючСО" in code


def test_so_book_resolves_all_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    a = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АПС/ИЗМ0/a.doc", "СО", HEADERS_A)
    b = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АПС/ИЗМ0/b.doc", "СО", HEADERS_B)
    result = query_builder.build_queries([a, b], db, out_dir=str(tmp_path / "out"))
    assert len(result["books"]) == 1
    book = result["books"][0]
    assert book["doc_type"] == "СО" and book["rows"] == 2
    assert book["unresolved_headers"] == []
    wb = openpyxl.load_workbook(book["path"])
    ws = wb["СписокСО"]
    assert len(list(ws[ws.tables["СписокСО"].ref])) == 3  # заголовок и две строки
    # написания из CSV попали в справочник колонок под своими ролями
    ref = wb["Справочники"]
    columns = {c.value: [r[c.column - 1].value for r in ref.iter_rows(min_row=2) if r[c.column - 1].value]
               for c in ref[1]}
    assert "Поз." in columns["NПП"] and "Завод-изготовитель" in columns["Поставщик"]
    assert "Коли- чест- во" in columns["КолВо"]


def test_vor_and_so_make_two_books(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    a = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АПС/ИЗМ0/a.doc", "СО", HEADERS_A)
    b = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АПС/ИЗМ0/b.docx", "ВОР",
             ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"])
    result = query_builder.build_queries([a, b], db, out_dir=str(tmp_path / "out"))
    assert sorted(b["doc_type"] for b in result["books"]) == ["ВОР", "СО"]
