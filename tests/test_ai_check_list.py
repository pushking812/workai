import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ai_check_list", Path(__file__).resolve().parents[1] / "scripts" / "ai_check_list.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_groups_by_room_and_sorts_by_priority():
    rows = [
        ("a.pdf", "1", "Назначение", "x", "y"),
        ("a.pdf", "2", "Номер_правоуст", "1", "2"),
        ("a.pdf", "3", "Площадь_м2", "1,0", 2.0),
        ("a.pdf", "3", "Назначение", "x", "y"),
    ]
    res = mod.build(rows)
    assert [r[2] for r in res] == ["3", "2", "1"]
    assert res[0][0] == 1 and res[0][3] == "Площадь_м2; Назначение"
    assert res[2][0] == 3
