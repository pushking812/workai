"""«Сформировать запросы» в режиме ВОР+СО: одна книга, два списка CSV."""

from __future__ import annotations

import importlib
import os

import openpyxl
import pytest

from api.controller import Controller
from core import database, query_builder

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOR_TEMPLATE = os.path.join(ROOT, query_builder.TEMPLATES["ВОР"]["path"])
SO_TEMPLATE = os.path.join(ROOT, query_builder.TEMPLATES["СО"]["path"])
pytestmark = pytest.mark.skipif(
    not (os.path.isfile(VOR_TEMPLATE) and os.path.isfile(SO_TEMPLATE)), reason="нет шаблонов ВОР и СО")

VOR_HEADERS = ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"]
SO_HEADERS = ["Поз.", "Наименование и техническая характеристика", "Ед. изм.", "Кол-во"]


def _add(db, tmp_path, name, doc_type, headers):
    connection = database.init_db(db)
    try:
        file_id = database.add_file(
            connection, "h_" + name, str(tmp_path / "РД" / "ЕСТ-ПМ-80825-Р-1-АПС" / "ИЗМ0" / name), name,
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


@pytest.fixture()
def combined(tmp_path, monkeypatch):
    """Шаблон ВОР+СО без запросов (структура книги), собранный во временную папку."""
    monkeypatch.syspath_prepend(os.path.join(ROOT, "scripts"))
    monkeypatch.chdir(ROOT)
    module = importlib.import_module("make_combined_template")
    target = str(tmp_path / "шаблон ВОР+СО.xlsx")
    monkeypatch.setattr(module, "TARGET", target)
    module.build()
    return {**query_builder.COMBINED_TEMPLATE, "path": target}


def _rows(ws, table):
    return list(ws[ws.tables[table].ref])


def test_combined_fills_both_lists(tmp_path, combined):
    db = str(tmp_path / "t.db")
    vor = _add(db, tmp_path, "a.docx", "ВОР", VOR_HEADERS)
    so1 = _add(db, tmp_path, "b.doc", "СО", SO_HEADERS)
    so2 = _add(db, tmp_path, "c.doc", "СО", SO_HEADERS)
    result = query_builder.build_queries(
        [vor, so1, so2], db, out_dir=str(tmp_path / "out"), mode=query_builder.MODE_COMBINED, combined=combined)
    assert len(result["books"]) == 1
    book = result["books"][0]
    assert book["doc_type"] == "ВОР+СО" and book["rows_by_type"] == {"ВОР": 1, "СО": 2}
    assert os.path.basename(book["path"]).startswith("ВОР+СО_")
    wb = openpyxl.load_workbook(book["path"])
    assert len(_rows(wb["СписокВОР"], "СписокВОР")) == 2  # шапка и одна строка
    so_rows = _rows(wb["СписокСО"], "СписокСО")
    assert len(so_rows) == 3
    assert so_rows[1][3].value.endswith("_table_1.csv")


def test_combined_needs_both_types(tmp_path, combined):
    db = str(tmp_path / "t.db")
    vor = _add(db, tmp_path, "a.docx", "ВОР", VOR_HEADERS)
    with pytest.raises(query_builder.QueryBuildError, match="СО"):
        query_builder.build_queries(
            [vor], db, out_dir=str(tmp_path / "out"), mode=query_builder.MODE_COMBINED, combined=combined)


def test_controller_reports_combined_error(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    vor = _add(db, tmp_path, "a.docx", "ВОР", VOR_HEADERS)
    result = Controller(db).build_queries([vor], opener=lambda p: None, mode="combined")
    assert result["status"] == "error" and "СО" in result["message"]


def test_unknown_mode_is_error(tmp_path):
    db = str(tmp_path / "t.db")
    vor = _add(db, tmp_path, "a.docx", "ВОР", VOR_HEADERS)
    with pytest.raises(query_builder.QueryBuildError):
        query_builder.build_queries([vor], db, out_dir=str(tmp_path / "out"), mode="x")
