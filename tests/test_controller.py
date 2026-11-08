"""API-слой (Этап 3.6) и остановка долгого поиска (Этап 3.7)."""

from __future__ import annotations

import time

from api.controller import Controller
from core import database
from core.search.manager import SearchManager
from core.search.registrar import FileRegistrar
from core.search.tasks import TaskManager


def _make(tmp_path, delay=0.0):
    db = str(tmp_path / "t.db")

    def reader(path):
        if delay:
            time.sleep(delay)
        name = path.replace("\\", "/").split("/")[-1]
        return {
            "doc_code": f"CODE-{name}",
            "revision": "0",
            "revision_date": "2025-08-01",
            "stamp_status": "OK",
        }

    registrar = FileRegistrar(db, reader)
    tasks = TaskManager(db, saver=lambda *args: "x.csv")
    return Controller(db, SearchManager(), tasks, registrar), db


def test_start_search_blocking_and_files(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    for i in range(3):
        (folder / f"f{i}_ВОР.docx").write_bytes(bytes([i]))
    ctl, _ = _make(tmp_path)
    assert ctl.start_search([str(folder)], "*ВОР*", background_mode=False) == {"status": "started"}
    status = ctl.get_status()
    assert status["search"]["total_found"] == 3
    assert not status["search"]["running"]
    data = ctl.get_files()
    assert len(data["files"]) == 3
    assert {i["ui_status"] for i in data["found"]} == {"FOUND"}


def test_start_search_validation_and_double_start(tmp_path):
    ctl, _ = _make(tmp_path, delay=0.2)
    assert ctl.start_search([])["status"] == "error"
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.docx").write_bytes(b"a")
    assert ctl.start_search(str(folder))["status"] == "started"
    assert ctl.start_search(str(folder))["status"] == "already_running"
    ctl.search.wait(10)


def test_process_selected_saves_files(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.docx").write_bytes(b"a")
    ctl, db = _make(tmp_path)
    ctl.start_search(str(folder), background_mode=False)
    ids = [f["id"] for f in ctl.get_files()["files"]]
    assert ctl.process_selected(ids) == {"status": "started", "queued": 1}
    assert ctl.tasks.wait(10)
    assert ctl.get_status()["tasks"]["processed"] == 1


def test_stop_long_search_keeps_partial_result(tmp_path):
    folder = tmp_path / "big"
    folder.mkdir()
    for i in range(40):
        (folder / f"f{i}.docx").write_bytes(bytes([i]))
    ctl, db = _make(tmp_path, delay=0.1)
    assert ctl.start_search(str(folder))["status"] == "started"
    time.sleep(1)
    assert ctl.stop_search() == {"status": "stopping"}
    assert ctl.search.wait(10)
    status = ctl.get_status()["search"]
    assert status["stopped"] and not status["running"]
    connection = database.init_db(db)
    try:
        saved = len(database.list_files(connection))
    finally:
        connection.close()
    assert 0 < saved < 40
