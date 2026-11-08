"""Мост PyWebView (Этап 4): `Api` делегирует в controller; ручное добавление."""

from __future__ import annotations

import os

from api import controller, webview_api
from api.controller import Controller
from api.webview_api import Api
from core.search.manager import SearchManager
from core.search.registrar import FileRegistrar
from core.search.tasks import TaskManager

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


def _controller(tmp_path):
    db = str(tmp_path / "t.db")
    reader = lambda path: {  # noqa: E731
        "doc_code": "CODE-1", "revision": "0", "revision_date": "2025-08-01", "stamp_status": "OK",
    }
    return Controller(db, SearchManager(), TaskManager(db, saver=lambda *a: "x.csv"), FileRegistrar(db, reader))


def test_ping():
    assert Api().ping() == "pong"


def test_api_delegates_to_controller(monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "get_status", lambda: calls.append("status") or {"ok": 1})
    monkeypatch.setattr(controller, "stop_search", lambda: calls.append("stop") or {"s": 1})
    monkeypatch.setattr(controller, "add_files", lambda paths: calls.append(("add", paths)) or {"added": 2})
    monkeypatch.setattr(controller, "process_selected", lambda ids: calls.append(("save", ids)) or {})
    api = Api()
    assert api.get_status() == {"ok": 1}
    assert api.stop_search() == {"s": 1}
    assert api.process_manual_add(["a", "b"]) == {"added": 2}
    api.process_selected([1, 2])
    assert calls == ["status", "stop", ("add", ["a", "b"]), ("save", [1, 2])]


def test_dialogs_without_window(monkeypatch):
    monkeypatch.setattr(webview_api, "_first_window", lambda: None)
    import pytest

    pytest.importorskip("webview")
    assert Api().add_files_dialog() == []
    assert Api().choose_folder() == ""


def test_add_files_and_stat(tmp_path):
    ctl = _controller(tmp_path)
    first = tmp_path / "a.docx"
    first.write_bytes(b"abc")
    result = ctl.add_files([str(first), str(tmp_path / "missing.docx")])
    assert result["added"] == 1
    assert len(result["errors"]) == 1
    data = ctl.get_files()
    row = next(r for r in data["files"] if r["path"].endswith("a.docx"))
    assert row["size"] == 3
    assert row["file_mtime"] is not None
    assert data["found"][0]["filename"] == "a.docx"


def test_hide_and_restore(tmp_path):
    ctl = _controller(tmp_path)
    first = tmp_path / "a.docx"
    first.write_bytes(b"abc")
    ctl.add_files([str(first)])
    file_id = ctl.get_files()["files"][0]["id"]
    assert ctl.hide_files([file_id, 9999]) == {"status": "ok", "changed": 1}
    assert ctl.get_files()["files"][0]["status"] == "HIDDEN"
    assert ctl.hide_files([file_id])["changed"] == 0
    assert ctl.restore_files([file_id])["changed"] == 1
    assert ctl.get_files()["files"][0]["status"] == "SAVED"
    assert ctl.restore_files([file_id])["changed"] == 0


def test_clear_database_removes_records_and_csv(tmp_path):
    ctl = _controller(tmp_path)
    first = tmp_path / "a.docx"
    first.write_bytes(b"abc")
    ctl.add_files([str(first)])
    file_id = ctl.get_files()["files"][0]["id"]
    csv = tmp_path / "x.csv"
    csv.write_text("a;b", encoding="utf-8")
    from core import database

    connection = database.init_db(ctl.db_path)
    database.update_file_status(connection, file_id, "SAVED", csv_path=str(csv))
    connection.close()
    result = ctl.clear_database()
    assert result["status"] == "ok"
    assert result["records"] == 1
    assert result["csv_deleted"] == 1
    assert not csv.exists()
    assert ctl.get_files() == {"files": [], "found": []}


def test_api_new_methods_delegate(monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "hide_files", lambda ids: calls.append(("hide", ids)) or {})
    monkeypatch.setattr(controller, "restore_files", lambda ids: calls.append(("restore", ids)) or {})
    monkeypatch.setattr(controller, "clear_database", lambda: calls.append("clear") or {})
    api = Api()
    api.hide_files([1])
    api.restore_files([2])
    api.clear_database()
    assert calls == [("hide", [1]), ("restore", [2]), "clear"]


def test_ui_files_exist():
    for name in ("index.html", os.path.join("css", "style.css"), os.path.join("js", "app.js")):
        assert os.path.isfile(os.path.join(UI_DIR, name))
