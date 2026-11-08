import threading
import time

from core.search.manager import SearchManager


def _make_files(tmp_path, count):
    for i in range(count):
        (tmp_path / f"{i:03d}_ВОР.docx").write_bytes(b"x")


def test_search_collects_files(tmp_path):
    _make_files(tmp_path, 5)
    manager = SearchManager()
    assert manager.start_search([str(tmp_path)], "*ВОР*")
    assert manager.wait(5)
    status = manager.get_status()
    assert status["total_found"] == 5
    assert status["processed_files"] == 5
    assert not status["running"]
    assert not status["stopped"]


def test_second_start_ignored_while_running(tmp_path):
    _make_files(tmp_path, 3)
    release = threading.Event()
    manager = SearchManager()
    assert manager.start_search([str(tmp_path)], "*", on_file=lambda p: release.wait(5))
    assert not manager.start_search([str(tmp_path)], "*")
    release.set()
    assert manager.wait(5)


def test_stop_interrupts_search(tmp_path):
    _make_files(tmp_path, 50)
    manager = SearchManager()
    manager.start_search([str(tmp_path)], "*", on_file=lambda p: time.sleep(0.05))
    time.sleep(0.2)
    manager.stop_search()
    assert manager.wait(5)
    status = manager.get_status()
    assert status["stopped"]
    assert 0 < status["processed_files"] < 50


def test_callback_error_does_not_stop_search(tmp_path):
    _make_files(tmp_path, 3)

    def boom(path):
        raise ValueError("bad")

    manager = SearchManager()
    manager.start_search([str(tmp_path)], "*", on_file=boom)
    assert manager.wait(5)
    status = manager.get_status()
    assert status["processed_files"] == 3
    assert len(status["errors"]) == 3


def test_restart_after_finish(tmp_path):
    _make_files(tmp_path, 2)
    manager = SearchManager()
    manager.start_search([str(tmp_path)])
    manager.wait(5)
    assert manager.start_search([str(tmp_path)])
    manager.wait(5)
    assert manager.get_status()["total_found"] == 2


def test_singleton():
    assert SearchManager.get_instance() is SearchManager.get_instance()
