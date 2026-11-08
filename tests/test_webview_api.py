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


def test_ui_files_exist():
    for name in ("index.html", os.path.join("css", "style.css"), os.path.join("js", "app.js")):
        assert os.path.isfile(os.path.join(UI_DIR, name))
