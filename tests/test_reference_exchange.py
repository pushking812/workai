"""Обмен справочником с Excel и перенос экспликаций помещений."""
import sqlite3

import openpyxl
import pytest

from core import reference_exchange as ex
from core import reference_store as rs


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    monkeypatch.setattr(rs, "USAGES", [])
    monkeypatch.setattr(rs, "SEED_PATH", tmp_path / "нет.xlsx")
    rs.ensure_tables(c, seed=False)
    yield c
    c.close()


def _rec(b="СЕН", f="ПС3", f_name="3 подземный этаж", r="1", name="Релейная", area=10.5):
    return {"b": b, "f": f, "f_name": f_name, "f_ground": "подземный", "r": r, "r_name": name, "area": area}


def test_floor_code_for_station_floors():
    assert ex.floor_code_for("ПС", "3 подземный этаж") == "ПС3"
    assert ex.floor_code_for("ПС", "Подвал") == "ПС"
    assert ex.floor_code_for("Э3", "3 этаж") == "Э3"


def test_records_duplicate_numbers_get_suffix(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Помещения"
    ws.append(["Здание_код", "Этаж_код", "Этаж_файл", "Наземный_подземный", "Номер_помещения",
               "Назначение", "Площадь_м2"])
    ws.append(["ДС1", "Э3", "3 этаж", "наземный", "350а", "А", 1])
    ws.append(["ДС1", "Э3", "3 этаж", "наземный", "350а", "Б", 2])
    ws.append(["СЕН", "ПС", "2 подземный этаж", "подземный", "1", "В", 3])
    ws.append(["СЕН", "ПС", "3 подземный этаж", "подземный", "1", "Г", 4])
    ws.append([None, None, None, None, "9", "пусто", 1])
    wb.save(tmp_path / "p.xlsx")
    recs = ex.records_from_rooms_xlsx(tmp_path / "p.xlsx")
    assert [r["r"] for r in recs] == ["350а", "350а (#2)", "1", "1"]
    assert [r["f"] for r in recs] == ["Э3", "Э3", "ПС2", "ПС3"]


def test_merge_into_db_adds_and_fills_only_empty(conn):
    b = rs.add_building(conn, "СЕН", "", "Сенная")
    f = rs.add_floor(conn, b, "ПС3", "", "подземный")
    rs.add_room(conn, f, "1", "", "")
    rs.add_room(conn, f, "2", "Своё имя", "")
    stat = ex.merge_into_db(conn, [_rec(r="1"), _rec(r="2", name="Другое", area=7), _rec(r="3"),
                                   _rec(f="ПС4", f_name="4 подземный этаж", r="1")])
    assert stat == {"floors": 1, "rooms": 2, "named": 1, "areas": 2}
    rooms = {(r["floor_id"], r["code"]): r for r in rs.list_reference(conn)["rooms"]}
    assert rooms[(f, "1")]["name"] == "Релейная" and rooms[(f, "1")]["area"] == 10.5
    assert rooms[(f, "2")]["name"] == "Своё имя" and rooms[(f, "2")]["area"] == 7
    assert ex.merge_into_db(conn, [_rec(r="1")]) == {"floors": 0, "rooms": 0, "named": 0, "areas": 0}


def test_export_import_roundtrip(conn, tmp_path):
    b = rs.add_building(conn, "ФСТ", "ст.Фрунзенская", "станция метро Фрунзенская")
    f = rs.add_floor(conn, b, "ПС2", "2 подземный этаж", "подземный")
    rs.add_room(conn, f, "5", "Камера", "", 12.34)
    path = tmp_path / "ref.xlsx"
    assert ex.export_xlsx(conn, path) == {"buildings": 1, "floors": 1, "rooms": 1}
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Здания", "Этажи", "Помещения"]

    other = sqlite3.connect(tmp_path / "o.db")
    other.row_factory = sqlite3.Row
    rs.ensure_tables(other, seed=False)
    res = ex.import_xlsx(other, path)
    assert res["added"] == {"buildings": 1, "floors": 1, "rooms": 1}
    assert rs.list_reference(other)["rooms"][0]["area"] == 12.34
    again = ex.import_xlsx(other, path)
    assert again["added"] == {"buildings": 0, "floors": 0, "rooms": 0}
    assert again["updated"] == {"buildings": 0, "floors": 0, "rooms": 0}
    other.close()


def test_import_updates_but_never_deletes(conn, tmp_path):
    b = rs.add_building(conn, "ФСТ", "", "")
    f = rs.add_floor(conn, b, "ПС", "", "")
    rs.add_room(conn, f, "5", "Старое", "")
    rs.add_room(conn, f, "6", "Останется", "")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Помещения"
    ws.append(ex.R_HEAD)
    ws.append(["ФСТ", "ПС", "5", "Новое", "подземный", 3.2])
    wb.save(tmp_path / "i.xlsx")
    res = ex.import_xlsx(conn, tmp_path / "i.xlsx")
    assert res["updated"]["rooms"] == 1
    rooms = {r["code"]: r for r in rs.list_reference(conn)["rooms"]}
    assert rooms["5"]["name"] == "Новое" and rooms["5"]["ground"] == "подземный" and rooms["5"]["area"] == 3.2
    assert "6" in rooms


def test_update_building_keeps_short_name(conn):
    b = rs.add_building(conn, "ФСТ", "ст.Фрунзенская", "полное")
    rs.update_building(conn, b, "ФСТ", None, "новое полное")
    row = rs.list_reference(conn)["buildings"][0]
    assert row["name"] == "ст.Фрунзенская" and row["full"] == "новое полное"


def test_merge_into_spravochniki(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Здания"
    wf = wb.create_sheet("Этажи")
    wf.append(["building_code", "floor_code", "floor_name", "Наземный/подземный"])
    wr = wb.create_sheet("Помещения")
    wr.append(["building_code", "floor_code", "room_code", "room_name", "Наземный/подземный"])
    wr.append(["СЕН", "ПС3", "1", None, "наследуется от этажа"])
    wb.save(tmp_path / "s.xlsx")
    stat = ex.merge_into_spravochniki(tmp_path / "s.xlsx", [_rec(r="1"), _rec(r="2")])
    assert stat == {"floors": 1, "rooms": 1, "named": 1, "areas": 1}
    wr = openpyxl.load_workbook(tmp_path / "s.xlsx")["Помещения"]
    assert wr.cell(1, 6).value == "Площадь_м2"
    assert [wr.cell(i, 4).value for i in (2, 3)] == ["Релейная", "Релейная"]
