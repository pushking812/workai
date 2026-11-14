from api.controller import Controller


def test_reconcile_report_opens_file(tmp_path):
    opened = []
    c = Controller(db_path=str(tmp_path / "x.db"))
    res = c.reconcile_report(opener=opened.append, runner=lambda folder: {"status": "ok", "path": "a.xlsx"})
    assert res["status"] == "ok" and opened == ["a.xlsx"]


def test_reconcile_report_error_not_opened(tmp_path):
    opened = []
    c = Controller(db_path=str(tmp_path / "x.db"))
    res = c.reconcile_report(opener=opened.append, runner=lambda folder: {"status": "error", "message": "m"})
    assert res["status"] == "error" and not opened


def test_make_reconcile_report_no_set(tmp_path):
    from core import excel_refresh
    res = excel_refresh.make_reconcile_report(str(tmp_path))
    assert res["status"] == "error" and "комплекта" in res["message"]
