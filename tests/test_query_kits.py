"""«Сформировать запросы»: одна книга на тип, ключи комплекта берутся из пути."""

from __future__ import annotations

import os

import pytest

from core import database, query_builder

TEMPLATE = query_builder.TEMPLATES["ВОР"]["path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(TEMPLATE), reason="нет шаблона ВОР")


def _add(db, tmp_path, rel, doc_code, revision, stamp_date, doc_type="ВОР"):
    connection = database.init_db(db)
    try:
        path = str(tmp_path / rel)
        name = os.path.basename(rel)
        file_id = database.add_file(
            connection, "h_" + rel.replace("\\", "_").replace("/", "_"), path, name,
            {"doc_code": doc_code, "doc_type": doc_type, "revision": revision,
             "revision_date": "2026-06-01", "stamp_date": stamp_date,
             "revision_date_source": "stamp", "stamp_status": "OK"},
        )
        csv = tmp_path / f"h_{file_id}_table_1.csv"
        csv.write_text("a;b\n1;2\n", encoding="utf-8-sig")
        connection.execute("UPDATE files SET csv_path = ? WHERE id = ?", (str(csv), file_id))
        connection.commit()
        return file_id
    finally:
        connection.close()


def test_one_book_per_type_with_kit_keys_in_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    # шифр в штампе без «-Р-» — ключ всё равно берётся из папки комплекта
    a = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АЭК/ИЗМ1/a.docx", "ЕСТ-ПМ-80825-1-АЭК.ВОР", "1", "2026-06-01")
    b = _add(db, tmp_path, "РД/ЕСТ-ПМ-80825-Р-1-АПС/ИЗМ0/b.docx", "ЕСТ-ПМ-80825-Р-1-АПС.ВОР", "0", "2026-09-17")
    result = query_builder.build_queries([a, b], db, out_dir=str(tmp_path / "out"))
    books = result["books"]
    assert len(books) == 1
    assert books[0]["files"] == 2 and books[0]["rows"] == 2
    kits = {(k["code"], k["revision"], k["date"]) for k in books[0]["kits"]}
    assert kits == {("ЕСТ-ПМ-80825-Р-1-АЭК", 1, "2026-06-01"), ("ЕСТ-ПМ-80825-Р-1-АПС", 0, "2026-09-17")}

    import openpyxl
    ws = openpyxl.load_workbook(books[0]["path"])["СписокВОР"]
    rows = [[c.value for c in r] for r in ws[ws.tables["СписокВОР"].ref][1:]]
    assert {(r[0], r[1], r[2].strftime("%Y-%m-%d")) for r in rows} == {
        ("ЕСТ-ПМ-80825-Р-1-АЭК", 1, "2026-06-01"), ("ЕСТ-ПМ-80825-Р-1-АПС", 0, "2026-09-17")}
