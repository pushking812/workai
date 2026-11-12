"""«Сформировать запросы»: копия шаблона ВОР со списком CSV выбранных файлов."""

from __future__ import annotations

import os
import zipfile

import pytest

from api.controller import Controller
from core import database, query_builder

TEMPLATE = query_builder.TEMPLATES["ВОР"]["path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(TEMPLATE), reason="нет шаблона ВОР")


def _add(db, tmp_path, name, doc_type="ВОР", tables=(1,), with_csv=True, revision="1", **extra):
    connection = database.init_db(db)
    try:
        file_id = database.add_file(
            connection, "h_" + name, str(tmp_path / name), name,
            {"doc_code": f"ЕСТ-ПМ-1-СС.{doc_type}", "project_code": "ЕСТ-ПМ", "section_code": "1-СС",
             "doc_type": doc_type, "revision": revision, "revision_date": "2026-05-07",
             "sheet": 1, "sheets_total": 5, "stamp_status": "OK"},
        )
        paths = []
        for number in tables:
            csv = tmp_path / f"h_{name}_table_{number}.csv"
            if with_csv:
                csv.write_text("a;b\n1;2\n", encoding="utf-8-sig")
            paths.append(str(csv))
        connection.execute("UPDATE files SET csv_path = ? WHERE id = ?", (";".join(paths), file_id))
        connection.commit()
        return file_id
    finally:
        connection.close()


def _ctl(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    return Controller(db), db


def _table(path):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb["СписокВОР"]
    ref = ws.tables["СписокВОР"].ref
    rows = [[c.value for c in r] for r in ws[ref]]
    return ref, rows[0], rows[1:]


def test_build_fills_table_one_row_per_csv(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    a = _add(db, tmp_path, "a.docx", tables=(1, 2))
    b = _add(db, tmp_path, "b.docx")
    opened = []
    result = ctl.build_queries([a, b], opener=opened.append)
    assert result["status"] == "ok" and result["skipped"] == []
    book = result["books"][0]
    assert (book["files"], book["rows"]) == (2, 3) and opened == [book["path"]]

    ref, header, rows = _table(book["path"])
    assert ref == "A15:R18"
    assert header[:5] == ["ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ПутьФайла", "Загружать"]
    first = dict(zip(header, rows[0]))
    assert first["ШифрПроекта"] == "ЕСТ-ПМ-1-СС"  # без «.ВОР», как в шаблоне
    assert first["НомИзмПроекта"] == 1 and first["Загружать"] == 1
    assert first["ДатаИзм"].strftime("%Y-%m-%d") == "2026-05-07"
    assert first["ПутьФайла"].endswith("h_a.docx_table_1.csv") and os.path.isabs(first["ПутьФайла"])
    assert first["ИмяФайла"] == "a.docx" and first["Таблица"] == 1
    assert [r[header.index("Таблица")] for r in rows] == [1, 2, 1]


def test_build_keeps_power_query_and_other_sheets(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    book = ctl.build_queries([_add(db, tmp_path, "a.docx")], opener=lambda p: None)["books"][0]["path"]
    with zipfile.ZipFile(TEMPLATE) as src, zipfile.ZipFile(book) as dst:
        assert src.namelist() == dst.namelist()
        changed = {n for n in src.namelist() if src.read(n) != dst.read(n)}
    # список файлов (лист + таблица) и справочник колонок (лист; таблица, если изменился диапазон)
    assert 3 <= len(changed) <= 4 and all(n.startswith(("xl/worksheets/", "xl/tables/")) for n in changed)


def _reference(path):
    import openpyxl
    ws = openpyxl.load_workbook(path)["Справочники"]
    ref = ws.tables["СправочникКолонок"].ref
    rows = [[c.value for c in r] for r in ws[ref]]
    return ref, {role: [r[i] for r in rows[1:] if r[i]] for i, role in enumerate(rows[0])}


def test_reference_gets_variants_from_csv_headers(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _add(db, tmp_path, "a.docx")
    csv = tmp_path / "h_a.docx_table_1.csv"
    csv.write_text("№ п/п;№ в ЛСР;Наименование работ;Ед. изм.;Кол-во;Мой столбец\n1;2;3;4;5;6\n",
                   encoding="utf-8-sig")
    result = ctl.build_queries([file_id], opener=lambda p: None)
    book = result["books"][0]
    assert book["unresolved_headers"] == ["Мой столбец"]
    ref, roles = _reference(book["path"])
    assert ref == "A1:G%d" % max(2, 1 + max(len(v) for v in roles.values()))
    assert "№ п/п" in roles["NПП"] and "№ в ЛСР" in roles["NВЛСР"]  # NЛСР -> роль шаблона
    assert "Кол-во" in roles["КолВо"] and "Ед. изм." in roles["ЕдИзм"]
    # варианты шаблона не потеряны и не дублируются
    assert len(roles["КолВо"]) == len(set(roles["КолВо"]))


def test_build_skips_other_types_and_missing_csv(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    ok = _add(db, tmp_path, "a.docx")
    svor = _add(db, tmp_path, "s.docx", doc_type="СВОР")
    no_csv = _add(db, tmp_path, "n.docx", with_csv=False)
    result = ctl.build_queries([ok, svor, no_csv], opener=lambda p: None)
    assert result["status"] == "ok" and result["books"][0]["files"] == 1
    reasons = {s["id"]: s["reason"] for s in result["skipped"]}
    assert "СВОР" in reasons[svor] and "CSV не найден" in reasons[no_csv]


def test_build_errors_when_nothing_suitable(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    assert ctl.build_queries([])["status"] == "error"
    result = ctl.build_queries([_add(db, tmp_path, "s.docx", doc_type="СВОР")])
    assert result["status"] == "error" and "СВОР" in result["message"]


def test_non_numeric_revision_written_as_text(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _add(db, tmp_path, "x.docx", revision="Х")
    book = ctl.build_queries([file_id], opener=lambda p: None)["books"][0]["path"]
    _ref, header, rows = _table(book)
    assert rows[0][header.index("НомИзмПроекта")] == "Х"
