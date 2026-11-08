"""Привязка сканера к БД (Этап 3.4)."""

from __future__ import annotations

from core import database
from core.search.manager import SearchManager
from core.search.registrar import FileRegistrar

CODE = "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"


def _reader(stamps):
    def read(path):
        return dict(stamps[path.replace("\\", "/").split("/")[-1]])

    return read


def _stamp(revision="0", date="2025-08-01", code=CODE):
    return {"doc_code": code, "revision": revision, "revision_date": date, "stamp_status": "OK"}


def _run(tmp_path, registrar):
    manager = SearchManager()
    assert manager.start_search([str(tmp_path)], "*ВОР*", on_file=registrar)
    assert manager.wait(10)
    return manager


def test_new_file_saved_and_found(tmp_path):
    (tmp_path / "a_ВОР.docx").write_bytes(b"a")
    db = str(tmp_path / "t.db")
    registrar = FileRegistrar(db, _reader({"a_ВОР.docx": _stamp()}))
    manager = _run(tmp_path, registrar)
    assert not manager.errors
    items = registrar.get_items()
    assert [i["ui_status"] for i in items] == ["FOUND"]
    conn = database.init_db(db)
    try:
        row = database.get_file_by_id(conn, items[0]["file_id"])
    finally:
        conn.close()
    assert row["status"] == "SAVED"


def test_rescan_gives_exists_without_new_records(tmp_path):
    (tmp_path / "a_ВОР.docx").write_bytes(b"a")
    db = str(tmp_path / "t.db")
    stamps = {"a_ВОР.docx": _stamp()}
    first = FileRegistrar(db, _reader(stamps))
    _run(tmp_path, first)
    second = FileRegistrar(db, _reader(stamps))
    _run(tmp_path, second)
    assert [i["ui_status"] for i in second.get_items()] == ["EXISTS"]
    assert second.get_items()[0]["file_id"] == first.get_items()[0]["file_id"]


def test_same_stamp_other_content_is_variant(tmp_path):
    (tmp_path / "a_ВОР.docx").write_bytes(b"a")
    (tmp_path / "b_ВОР.docx").write_bytes(b"b")
    db = str(tmp_path / "t.db")
    stamps = {"a_ВОР.docx": _stamp(), "b_ВОР.docx": _stamp()}
    registrar = FileRegistrar(db, _reader(stamps))
    _run(tmp_path, registrar)
    assert sorted(i["ui_status"] for i in registrar.get_items()) == ["FOUND", "VARIANTS"]


def test_new_revision_is_found(tmp_path):
    (tmp_path / "a_ВОР.docx").write_bytes(b"a")
    (tmp_path / "b_ВОР.docx").write_bytes(b"b")
    db = str(tmp_path / "t.db")
    stamps = {"a_ВОР.docx": _stamp("0"), "b_ВОР.docx": _stamp("1", "2025-09-01")}
    registrar = FileRegistrar(db, _reader(stamps))
    _run(tmp_path, registrar)
    assert [i["ui_status"] for i in registrar.get_items()] == ["FOUND", "FOUND"]


def test_stamp_error_goes_to_manager_errors(tmp_path):
    (tmp_path / "a_ВОР.docx").write_bytes(b"a")

    def broken(path):
        raise RuntimeError("плохой файл")

    registrar = FileRegistrar(str(tmp_path / "t.db"), broken)
    manager = _run(tmp_path, registrar)
    assert len(manager.errors) == 1
    assert registrar.get_items() == []
