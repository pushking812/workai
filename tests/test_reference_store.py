"""Справочник зданий, этажей и помещений в БД: наполнение, правка, запреты."""
import sqlite3

import pytest

from core import reference_store as rs


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    monkeypatch.setattr(rs, "USAGES", [])
    monkeypatch.setattr(rs, "SEED_PATH", tmp_path / "нет.xlsx")  # без наполнения из файла
    rs.ensure_tables(c, seed=False)
    yield c
    c.close()


def test_uid_assigned_stable_and_locked(conn):
    b, f, r = _tree(conn)
    get = lambda t, i: conn.execute(f"SELECT uid FROM {t} WHERE id = ?", (i,)).fetchone()[0]
    assert get("ref_buildings", b).startswith("BLD-")
    assert get("ref_floors", f).startswith("FLR-")
    before = get("ref_rooms", r)
    assert before.startswith("ROM-")
    rs.update_room(conn, r, "КЗ2501")
    assert get("ref_rooms", r) == before  # смена кода uid не трогает
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE ref_rooms SET uid = 'X' WHERE id = ?", (r,))
    assert rs.list_reference(conn)["rooms"][0]["uid"] == before


def _tree(c):
    b = rs.add_building(c, "ФСТ", "ст.Фрунзенская", "станция метро Фрунзенская")
    f = rs.add_floor(c, b, "ПС", "Помещения станции", "подземный")
    r = rs.add_room(c, f, "КЗ2500", "Камера затвора")
    return b, f, r


def test_seed_from_file(tmp_path):
    c = sqlite3.connect(tmp_path / "s.db")
    c.row_factory = sqlite3.Row
    rs.ensure_tables(c, seed=False)
    src = rs.Path(__file__).resolve().parent.parent / "spravochniki.xlsx"
    if not src.exists():
        pytest.skip("нет spravochniki.xlsx")
    assert rs.seed_from_file(c, src) is True
    assert rs.seed_from_file(c, src) is False  # повторно не наполняется
    data = rs.list_reference(c)
    assert len(data["buildings"]) >= 11 and len(data["floors"]) >= 27 and len(data["rooms"]) >= 210
    floors = {(f["building_id"], f["code"]): f for f in data["floors"]}
    codes = {b["id"]: b["code"] for b in data["buildings"]}
    by = {(codes[k[0]], k[1]): v for k, v in floors.items()}
    assert by[("ЗДЦ", "ЭП")]["ground"] == "подземный"   # правило пользователя
    assert by[("ДС1", "Э1")]["ground"] == "наземный"
    ref = rs.to_reference(c)
    assert ref.building_name("ФСТ")
    c.close()


def test_hierarchy_and_unique(conn):
    b, f, r = _tree(conn)
    with pytest.raises(rs.ReferenceError_):
        rs.add_building(conn, " фст ")
    with pytest.raises(rs.ReferenceError_):
        rs.add_room(conn, f, "кз 2500")
    with pytest.raises(rs.ReferenceError_):
        rs.add_floor(conn, b, "Э1", ground="выше")
    data = rs.list_reference(conn)
    assert data["rooms"][0]["effective_ground"] == "подземный"
    rs.update_room(conn, r, "КЗ2500", "Камера", "наземный")
    assert rs.list_reference(conn)["rooms"][0]["effective_ground"] == "наземный"


def test_delete_used_is_refused(conn):
    b, f, r = _tree(conn)
    with pytest.raises(rs.ReferenceError_):
        rs.delete_building(conn, b)
    with pytest.raises(rs.ReferenceError_):
        rs.delete_floor(conn, f)
    rs.delete_room(conn, r)
    rs.delete_floor(conn, f)
    rs.delete_building(conn, b)
    assert rs.list_reference(conn)["buildings"] == []


def test_rename_propagates_to_registered_tables(conn):
    conn.execute("CREATE TABLE trassy (id INTEGER, bld TEXT, flr TEXT, room TEXT)")
    conn.executemany("INSERT INTO trassy VALUES (?, ?, ?, ?)", [
        (1, "ФСТ", "ПС", "КЗ2500"), (2, "ФСТ", "ПС", "КЗ0000"), (3, "ДС1", "ПС", "КЗ2500")])
    rs.register_usage(rs.Usage("trassy", "bld", "flr", "room", "Трассы"))
    b, f, r = _tree(conn)
    # используемые значения удалять нельзя, даже если дочерних нет
    rs.add_building(conn, "ДС1")
    b2 = conn.execute("SELECT id FROM ref_buildings WHERE code='ДС1'").fetchone()[0]
    with pytest.raises(rs.ReferenceError_, match="Трассы: 1"):
        rs.delete_building(conn, b2)
    rs.update_room(conn, r, "КЗ-2500", "Камера затвора")
    rows = conn.execute("SELECT bld, flr, room FROM trassy ORDER BY id").fetchall()
    assert [tuple(x) for x in rows] == [("ФСТ", "ПС", "КЗ-2500"), ("ФСТ", "ПС", "КЗ0000"), ("ДС1", "ПС", "КЗ2500")]
    rs.update_floor(conn, f, "СТ", "Помещения станции", "подземный")
    assert conn.execute("SELECT COUNT(*) FROM trassy WHERE flr='СТ'").fetchone()[0] == 2
    rs.update_building(conn, b, "ФРН", "ст.Фрунзенская")
    assert conn.execute("SELECT COUNT(*) FROM trassy WHERE bld='ФРН'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM trassy WHERE bld='ФСТ'").fetchone()[0] == 0
    with pytest.raises(rs.ReferenceError_):
        rs.delete_room(conn, r)
