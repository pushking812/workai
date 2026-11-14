"""Автообновление книг по кнопке «Сформировать» в режиме ВОР+СО (Excel подменяется)."""

from api.controller import Controller
from core import query_builder


def _fake_build(monkeypatch):
    books = [{"path": p, "rows": 1} for p in ("ВОР_1.xlsx", "СО_1.xlsx", "ВОР+СО_1.xlsx")]
    monkeypatch.setattr(query_builder, "build_queries", lambda *a, **k: {"books": books, "skipped": []})


def test_refreshed_books_open_only_vor_so(tmp_path, monkeypatch):
    _fake_build(monkeypatch)
    opened, calls = [], []

    def refresher(paths):
        calls.append(paths)
        return {"status": "ok", "log": ""}

    result = Controller(str(tmp_path / "db.sqlite")).build_queries(
        [1], opener=opened.append, mode=query_builder.MODE_VOR_SO, refresher=refresher)
    assert calls == [["ВОР_1.xlsx", "СО_1.xlsx", "ВОР+СО_1.xlsx"]]
    assert opened == ["ВОР+СО_1.xlsx"]
    assert result["refresh"]["status"] == "ok"


def test_parse_issues_sums_counts_per_type():
    from core import excel_refresh

    log = ("OK ВОР_1.xlsx refreshed and saved in 3 s\n"
           "ISSUES ВОР+СО_1.xlsx: без пары=2;дубль номера в СО=5\n"
           "OK ВОР+СО_1.xlsx refreshed and saved in 9 s")
    assert excel_refresh.parse_issues(log) == {"без пары": 2, "дубль номера в СО": 5}
    assert excel_refresh.parse_issues("ISSUES x: ") == {}
    assert excel_refresh.parse_issues("") == {}


def test_busy_excel_opens_all_books(tmp_path, monkeypatch):
    _fake_build(monkeypatch)
    opened = []
    result = Controller(str(tmp_path / "db.sqlite")).build_queries(
        [1], opener=opened.append, mode=query_builder.MODE_VOR_SO,
        refresher=lambda paths: {"status": "busy", "log": ""})
    assert len(opened) == 3
    assert result["refresh"]["status"] == "busy"


def test_by_type_mode_does_not_refresh(tmp_path, monkeypatch):
    _fake_build(monkeypatch)

    def refresher(paths):
        raise AssertionError("не должно вызываться")

    opened = []
    Controller(str(tmp_path / "db.sqlite")).build_queries([1], opener=opened.append, refresher=refresher)
    assert len(opened) == 3
