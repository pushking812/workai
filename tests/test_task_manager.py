"""Очередь фоновых задач (Этап 3.5)."""

from __future__ import annotations

from core import database
from core.search.tasks import TaskManager
from core.transformer.schema_analyzer import analyze_and_save_schema


def _db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return str(tmp_path / "t.db")


def _add(db, name, status="SAVED", current=1):
    conn = database.init_db(db)
    try:
        file_id = database.add_file(conn, "h_" + name, "/x/" + name, name, status=status)
        database.set_is_current(conn, file_id, current)
        return file_id
    finally:
        conn.close()


def _row(db, file_id):
    conn = database.init_db(db)
    try:
        return database.get_file_by_id(conn, file_id)
    finally:
        conn.close()


def test_save_ok_and_error_continue(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    good, bad, after = _add(db, "good"), _add(db, "bad"), _add(db, "after")

    def saver(path, file_hash, connection, exports_dir):
        if path.endswith("bad"):
            raise RuntimeError("boom")
        return "a.csv;b.csv"

    manager = TaskManager(db, saver)
    assert manager.save_files([good, bad, after]) == 3
    assert manager.wait(10)
    assert _row(db, good)["status"] == "SAVED"
    assert _row(db, good)["csv_path"] == "a.csv;b.csv"
    assert _row(db, bad)["status"] == "ERROR"
    assert "boom" in _row(db, bad)["error_message"]
    assert _row(db, after)["status"] == "SAVED"
    status = manager.get_status()
    assert status["processed"] == 3 and status["pending"] == 0 and len(status["errors"]) == 1


def test_save_without_tables_is_error(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    file_id = _add(db, "empty")
    manager = TaskManager(db, lambda *args: "")
    manager.save_files([file_id])
    assert manager.wait(10)
    row = _row(db, file_id)
    assert row["status"] == "ERROR" and "таблицы" in row["error_message"]


def _with_schema(db, file_id, headers):
    conn = database.init_db(db)
    try:
        analyze_and_save_schema(conn, headers, "h_" + _row(db, file_id)["filename"])
    finally:
        conn.close()


def test_prepare_ready_and_needs_mapping(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    ready = _add(db, "ready")
    unknown = _add(db, "unknown")
    no_schema = _add(db, "noschema")
    _with_schema(db, ready, ["Наименование работ", "Количество"])
    _with_schema(db, unknown, ["Совсем другой заголовок"])

    manager = TaskManager(db)
    assert manager.prepare_files() == 3
    assert manager.wait(10)
    assert _row(db, ready)["status"] == "READY"
    assert _row(db, unknown)["status"] == "NEEDS_MAPPING"
    assert _row(db, no_schema)["status"] == "NEEDS_MAPPING"


def test_prepare_skips_non_current_and_other_statuses(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    old = _add(db, "old", current=0)
    failed = _add(db, "failed", status="ERROR")
    manager = TaskManager(db)
    assert manager.prepare_files() == 0
    assert manager.prepare_files([old, failed]) == 2
    assert manager.wait(10)
    assert _row(db, old)["status"] == "SAVED"
    assert _row(db, failed)["status"] == "ERROR"


def test_restart_after_finish(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    first, second = _add(db, "one"), _add(db, "two")
    manager = TaskManager(db, lambda *args: "x.csv")
    manager.save_files([first])
    assert manager.wait(10)
    manager.save_files([second])
    assert manager.wait(10)
    assert manager.get_status()["processed"] == 2


def test_saved_file_with_csv_is_not_saved_again(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    file_id = _add(db, "done")
    manager = TaskManager(db, lambda *args: str(csv))
    assert manager.save_files([file_id]) == 1
    assert manager.wait(10)
    assert manager.save_files([file_id]) == 0  # CSV на диске, файл не менялся
    csv.unlink()
    assert manager.save_files([file_id]) == 1  # CSV потерян — сохраняем заново
    assert manager.wait(10)
