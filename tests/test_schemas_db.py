"""Таблица `schemas` и привязка файлов к схеме (Этап 2, коммит 1)."""

from __future__ import annotations

import sqlite3

from core import database as db


def _connect(tmp_path):
    return db.init_db(str(tmp_path / "t.db"))


def test_init_creates_schemas_table(tmp_path):
    con = _connect(tmp_path)
    columns = {row["name"] for row in con.execute("PRAGMA table_info(schemas)")}
    assert {"schema_hash", "raw_headers_json", "normalized_headers_json", "mapping_json"} <= columns
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_save_schema_roundtrip_and_no_overwrite(tmp_path):
    con = _connect(tmp_path)
    assert db.save_schema(con, "h1", ["№ п/п", "Ед. изм."], ["NПП", "ЕдИзм"]) is True
    db.set_schema_mapping(con, "h1", {"NПП": "NПП"})
    assert db.save_schema(con, "h1", ["x"], ["x"]) is False
    schema = db.get_schema(con, "h1")
    assert schema["raw_headers"] == ["№ п/п", "Ед. изм."]
    assert schema["normalized_headers"] == ["NПП", "ЕдИзм"]
    assert schema["mapping"] == {"NПП": "NПП"}
    assert db.get_schema(con, "nope") is None


def test_files_linked_to_schema(tmp_path):
    con = _connect(tmp_path)
    first = db.add_file(con, "a" * 64, "p1.docx", "p1.docx")
    db.add_file(con, "b" * 64, "p2.docx", "p2.docx")
    db.save_schema(con, "h1", ["a"], ["A"])
    db.set_file_schema_hash(con, first, "h1")
    assert [f["id"] for f in db.get_files_by_schema(con, "h1")] == [first]


def test_init_adds_schema_hash_to_old_files_table(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(db.CREATE_FILES_TABLE.replace("    schema_hash     TEXT,\n", ""))
    old.commit()
    old.close()
    con = db.init_db(path)
    columns = {row["name"] for row in con.execute("PRAGMA table_info(files)")}
    assert "schema_hash" in columns
