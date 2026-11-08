"""Парсер таблиц DOCX, шапки и CSV (Этап 1, пп. 8–10, 12)."""

from __future__ import annotations

import csv

import pytest

from core import database
from core.parsers.docx_parser import (
    clean_cell_text,
    extract_headers,
    extract_tables_from_docx,
    is_numbering_row,
    save_table_to_csv,
)


# --- clean_cell_text -------------------------------------------------------


def test_clean_cell_text_joins_paragraphs():
    assert clean_cell_text(["№", "п/п"]) == "№ п/п"


def test_clean_cell_text_nested_lists():
    assert clean_cell_text([["Кабель", ["КВВГ", ""]], "5х1,5"]) == "Кабель КВВГ 5х1,5"


def test_clean_cell_text_newlines_tabs_and_spaces():
    assert clean_cell_text("  а\r\nб\t\tв   г д  ") == "а б в г д"


def test_clean_cell_text_none_and_empty():
    assert clean_cell_text(None) == ""
    assert clean_cell_text(["", [""]]) == ""


# --- is_numbering_row / extract_headers ------------------------------------


def test_is_numbering_row():
    assert is_numbering_row(["1", "2", "3", "4"])
    assert is_numbering_row(["1.", "2.", "3.", "4."])
    assert not is_numbering_row(["1", "3", "2"])
    assert not is_numbering_row(["№", "Наименование", "Ед."])
    assert not is_numbering_row(["1", "", "", ""])


def test_extract_headers_simple():
    table = [["№", "Наименование", "Ед."], ["1", "Кабель", "м"]]
    headers, start = extract_headers(table)
    assert headers == ["№", "Наименование", "Ед."]
    assert start == 1


def test_extract_headers_skips_numbering_row():
    table = [
        ["№ п/п", "Наименование", "Кол-во"],
        ["1", "2", "3"],
        ["1", "Кабель", "10"],
    ]
    headers, start = extract_headers(table)
    assert headers == ["№ п/п", "Наименование", "Кол-во"]
    assert start == 2


def test_extract_headers_multiline_header():
    table = [
        ["№", "Наименование", "Масса"],
        ["п/п", "", "единицы, кг"],
        ["1", "Кабель", "2"],
    ]
    headers, start = extract_headers(table)
    assert headers[0] == "№ п/п"
    assert headers[2] == "Масса единицы, кг"
    assert start == 2


def test_extract_headers_group_row_prefix():
    table = [
        ["", "Оборудование", ""],
        ["№", "Тип", "Кол-во"],
        ["1", "Камера", "4"],
    ]
    headers, start = extract_headers(table)
    assert headers[1:] == ["Оборудование Тип", "Оборудование Кол-во"]
    assert start == 2


def test_extract_headers_empty_table():
    assert extract_headers([]) == ([], 0)


# --- CSV -------------------------------------------------------------------


def test_save_table_to_csv_utf8_sig(tmp_path):
    table = [["№", "Наименование"], ["1", "Кабель; «КВВГ»"], ["2", "Труба"]]
    target = tmp_path / "out" / "t.csv"
    headers, start = extract_headers(table)
    save_table_to_csv(table, str(target), headers=headers, data_start=start)

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with open(target, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file, delimiter=";"))
    assert rows[0] == ["№", "Наименование"]
    assert rows[1] == ["1", "Кабель; «КВВГ»"]
    assert len(rows) == 3


# --- Интеграция ------------------------------------------------------------


def build_docx(path: str) -> None:
    """Минимальный docx без python-docx: одна таблица 4x3."""
    import zipfile

    cells = [
        ["№ п/п", "Наименование", "Кол-во"],
        ["1", "2", "3"],
        ["1", "Камера<br/>видеонаблюдения", "4"],
        ["2", "Кабель", "100"],
    ]

    def cell_xml(text: str) -> str:
        paragraphs = "".join(
            f"<w:p><w:r><w:t>{part}</w:t></w:r></w:p>" for part in text.split("<br/>")
        )
        return f"<w:tc>{paragraphs}</w:tc>"

    rows = "".join(
        "<w:tr>" + "".join(cell_xml(c) for c in row) + "</w:tr>" for row in cells
    )
    body = (
        "<w:p><w:r><w:t>Ведомость объёмов работ</w:t></w:r></w:p>"
        f"<w:tbl><w:tblPr/><w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>{rows}</w:tbl>"
        "<w:p><w:pPr><w:sectPr/></w:pPr></w:p>"
    )
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
        archive.writestr("word/document.xml", document)


def test_extract_tables_from_generated_docx(tmp_path):
    path = tmp_path / "doc.docx"
    build_docx(str(path))
    tables = extract_tables_from_docx(str(path))
    assert len(tables) == 1
    assert tables[0][2][1] == "Камера видеонаблюдения"


def test_process_folder_saves_record_and_csv(tmp_path, monkeypatch):
    from scripts import process_folder as pf

    folder = tmp_path / "docs"
    folder.mkdir()
    build_docx(str(folder / "doc.docx"))
    monkeypatch.setattr(pf, "EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setattr(pf, "CONVERTED_DIR", str(tmp_path / "converted"))
    db_path = str(tmp_path / "app.db")

    rows = pf.process_folder(str(folder), db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "SAVED"

    connection = database.init_db(db_path)
    try:
        records = database.list_files(connection)
    finally:
        connection.close()
    assert len(records) == 1
    assert records[0]["status"] == "SAVED"
    csv_path = records[0]["csv_path"]
    assert csv_path and csv_path.endswith(".csv")
    with open(csv_path, "rb") as file:
        assert file.read(3) == b"\xef\xbb\xbf"
    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        content = list(csv.reader(file, delimiter=";"))
    assert content[0] == ["№ п/п", "Наименование", "Кол-во"]
    assert content[1] == ["1", "Камера видеонаблюдения", "4"]

    # Повторный запуск ничего не меняет.
    pf.process_folder(str(folder), db_path)
    connection = database.init_db(db_path)
    try:
        assert len(database.list_files(connection)) == 1
    finally:
        connection.close()
