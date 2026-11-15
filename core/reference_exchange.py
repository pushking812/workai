"""Обмен справочником зданий/этажей/помещений с Excel.

- `export_xlsx` / `import_xlsx`: три листа «Здания», «Этажи», «Помещения» с теми же
  колонками, что в `spravochniki.xlsx` (плюс примечание этажа и площадь помещения).
  Связи между листами — по кодам, поэтому файл переносится между базами.
  Загрузка добавляет недостающее и обновляет названия, признак и площадь; ничего
  не удаляет и коды не переименовывает (переименование — в окне справочника).
- `records_from_rooms_xlsx` + `merge_into_db` / `merge_into_spravochniki`: перенос
  экспликаций из `data/exports/Помещения.xlsx` в справочник.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from core import reference_store as rs

B_HEAD = ["building_code", "building_name", "Полное название"]
F_HEAD = ["building_code", "floor_code", "floor_name", "Наземный/подземный", "Примечание"]
R_HEAD = ["building_code", "floor_code", "room_code", "room_name", "Наземный/подземный", "Площадь_м2"]
UID_HEAD = "ID"  # идентификатор записи (BLD-/FLR-/ROM-): при загрузке не читается, у новых записей создаётся свой
INHERIT = "наследуется от этажа"


def _s(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _ground_in(raw: str) -> str | None:
    """Значение признака из файла; None — текст не распознан (поле не трогаем)."""
    low = raw.strip().lower()
    if low in ("", INHERIT):
        return ""
    if low.startswith("подземн"):
        return "подземный"
    if low.startswith("наземн"):
        return "наземный"
    return None


# ---------- перенос экспликаций помещений ----------

# Код здания в экспликациях -> код в справочнике БД, если в окне код переименовали (ЗДЦ -> ЕДЦ).
BUILDING_ALIASES = {"ЗДЦ": "ЕДЦ"}


def _blank_name(value: Any) -> bool:
    """Название не задано: пусто или только прочерк-заглушка («-», «–», «—»)."""
    return _s(value).strip(" -–—") == ""


def floor_code_for(floor_code: str, floor_file: str) -> str:
    """Станции в экспликациях идут по этажам («3 подземный этаж»), а в справочнике у
    станции один этаж ПС: для каждого подземного этажа заводим ПС<N>."""
    m = re.match(r"\s*(\d+)\s*подзем", floor_file or "", re.IGNORECASE)
    if floor_code == "ПС" and m:
        return f"ПС{m.group(1)}"
    return floor_code


def records_from_rooms_xlsx(path: str | Path) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb["Помещения"].iter_rows(values_only=True))
    finally:
        wb.close()
    head = list(rows[0])
    idx = {name: head.index(name) for name in
           ("Здание_код", "Этаж_код", "Этаж_файл", "Наземный_подземный", "Номер_помещения",
            "Назначение", "Площадь_м2")}
    out, seen = [], {}
    for row in rows[1:]:
        get = lambda name: row[idx[name]]
        b, r = _s(get("Здание_код")), _s(get("Номер_помещения"))
        if not b or not r:
            continue
        f = floor_code_for(_s(get("Этаж_код")), _s(get("Этаж_файл")))
        n = seen[(b, f, r.casefold())] = seen.get((b, f, r.casefold()), 0) + 1
        out.append({
            "b": b, "f": f, "f_name": _s(get("Этаж_файл")),
            "f_ground": _s(get("Наземный_подземный")),
            # повтор номера на этаже (так в скане) получает суффикс, чтобы код был уникальным
            "r": r if n == 1 else f"{r} (#{n})",
            "r_name": _s(get("Назначение")), "area": get("Площадь_м2"),
        })
    return out


def merge_into_db(connection: sqlite3.Connection, records: list[dict[str, Any]]) -> dict[str, int]:
    rs.ensure_tables(connection)
    stat = {"floors": 0, "rooms": 0, "named": 0, "areas": 0}
    buildings = {rs._key(r["code"]): r["id"] for r in connection.execute("SELECT id, code FROM ref_buildings")}
    floors = {(r["building_id"], rs._key(r["code"])): r["id"]
              for r in connection.execute("SELECT id, building_id, code FROM ref_floors")}
    rooms = {(r["floor_id"], rs._key(r["code"])): r
             for r in connection.execute("SELECT id, floor_id, code, name, area FROM ref_rooms")}
    for rec in records:
        bid = buildings.get(rs._key(rec["b"]))
        if bid is None and rec["b"] in BUILDING_ALIASES:
            bid = buildings.get(rs._key(BUILDING_ALIASES[rec["b"]]))
        if bid is None:
            bid = buildings[rs._key(rec["b"])] = rs.add_building(connection, rec["b"], "", "")
        fid = floors.get((bid, rs._key(rec["f"])))
        if fid is None:
            fid = floors[(bid, rs._key(rec["f"]))] = rs.add_floor(
                connection, bid, rec["f"], rec["f_name"], _ground_in(rec["f_ground"]) or "")
            stat["floors"] += 1
        old = rooms.get((fid, rs._key(rec["r"])))
        if old is None:
            new_id = rs.add_room(connection, fid, rec["r"], rec["r_name"], "", rec["area"])
            rooms[(fid, rs._key(rec["r"]))] = connection.execute(
                "SELECT id, floor_id, code, name, area FROM ref_rooms WHERE id = ?", (new_id,)).fetchone()
            stat["rooms"] += 1
            continue
        if _blank_name(old["name"]) and rec["r_name"]:
            connection.execute("UPDATE ref_rooms SET name = ? WHERE id = ?", (rec["r_name"], old["id"]))
            stat["named"] += 1
        if old["area"] is None and rs._area(rec["area"]) is not None:
            connection.execute("UPDATE ref_rooms SET area = ? WHERE id = ?", (rs._area(rec["area"]), old["id"]))
            stat["areas"] += 1
    connection.commit()
    return stat


def merge_into_spravochniki(path: str | Path, records: list[dict[str, Any]]) -> dict[str, int]:
    import openpyxl

    wb = openpyxl.load_workbook(path)
    wf, wr = wb["Этажи"], wb["Помещения"]
    if _s(wr.cell(1, 6).value) != R_HEAD[5]:
        wr.cell(1, 6).value = R_HEAD[5]
    floors = {(_s(r[0].value), rs._key(_s(r[1].value))) for r in wf.iter_rows(min_row=2) if r[0].value}
    rooms = {}
    for row in wr.iter_rows(min_row=2):
        if row[0].value:
            rooms[(_s(row[0].value), rs._key(_s(row[1].value)), rs._key(_s(row[2].value)))] = row[0].row
    stat = {"floors": 0, "rooms": 0, "named": 0, "areas": 0}
    for rec in records:
        if (rec["b"], rs._key(rec["f"])) not in floors:
            wf.append([rec["b"], rec["f"], rec["f_name"], _ground_in(rec["f_ground"]) or rec["f_ground"]])
            floors.add((rec["b"], rs._key(rec["f"])))
            stat["floors"] += 1
        key = (rec["b"], rs._key(rec["f"]), rs._key(rec["r"]))
        area = rs._area(rec["area"])
        if key not in rooms:
            wr.append([rec["b"], rec["f"], rec["r"], rec["r_name"], INHERIT, area])
            rooms[key] = wr.max_row
            stat["rooms"] += 1
            continue
        n = rooms[key]
        if _blank_name(wr.cell(n, 4).value) and rec["r_name"]:
            wr.cell(n, 4).value = rec["r_name"]
            stat["named"] += 1
        if wr.cell(n, 6).value in (None, "") and area is not None:
            wr.cell(n, 6).value = area
            stat["areas"] += 1
    wb.save(path)
    return stat


# ---------- выгрузка / загрузка ----------

def export_xlsx(connection: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    import openpyxl

    data = rs.list_reference(connection)
    code = {b["id"]: b["code"] for b in data["buildings"]}
    fcode = {f["id"]: (code[f["building_id"]], f["code"]) for f in data["floors"]}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Здания"
    ws.append(B_HEAD + [UID_HEAD])
    for b in data["buildings"]:
        ws.append([b["code"], b["name"], b["full"], b["uid"]])
    ws = wb.create_sheet("Этажи")
    ws.append(F_HEAD + [UID_HEAD])
    for f in data["floors"]:
        ws.append([code[f["building_id"]], f["code"], f["name"], f["ground"], f["note"], f["uid"]])
    ws = wb.create_sheet("Помещения")
    ws.append(R_HEAD + [UID_HEAD])
    for r in data["rooms"]:
        b, f = fcode[r["floor_id"]]
        ws.append([b, f, r["code"], r["name"], r["ground"] or INHERIT, r["area"], r["uid"]])
    for sheet in wb:
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = min(
                60, max(12, *(len(_s(c.value)) + 2 for c in col[:200])))
    wb.save(path)
    return {"buildings": len(data["buildings"]), "floors": len(data["floors"]), "rooms": len(data["rooms"])}


def _table(wb, name: str, head: list[str]) -> list[dict[str, Any]]:
    if name not in wb.sheetnames:
        return []
    rows = list(wb[name].iter_rows(values_only=True))
    if not rows:
        return []
    names = [_s(h) for h in rows[0]]
    pos = {h: names.index(h) for h in head if h in names}
    out = []
    for row in rows[1:]:
        item = {h: (row[i] if i < len(row) else None) for h, i in pos.items()}
        if any(_s(v) for v in item.values()):
            out.append(item)
    return out


def import_xlsx(connection: sqlite3.Connection, path: str | Path) -> dict[str, Any]:
    import openpyxl

    rs.ensure_tables(connection)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        b_rows, f_rows, r_rows = _table(wb, "Здания", B_HEAD), _table(wb, "Этажи", F_HEAD), _table(wb, "Помещения", R_HEAD)
    finally:
        wb.close()
    if not (b_rows or f_rows or r_rows):
        raise rs.ReferenceError_("В файле нет листов «Здания», «Этажи», «Помещения» с данными.")
    added = {"buildings": 0, "floors": 0, "rooms": 0}
    updated = {"buildings": 0, "floors": 0, "rooms": 0}
    skipped: list[str] = []

    def building(code: str) -> int:
        row = connection.execute("SELECT id, code FROM ref_buildings").fetchall()
        for r in row:
            if rs._key(r["code"]) == rs._key(code):
                return r["id"]
        added["buildings"] += 1
        return rs.add_building(connection, code, "", "")

    for it in b_rows:
        code = _s(it.get("building_code"))
        if not code:
            continue
        bid = building(code)
        cur = connection.execute("SELECT name, full_name FROM ref_buildings WHERE id = ?", (bid,)).fetchone()
        name = _s(it["building_name"]) if "building_name" in it else cur["name"]
        full = _s(it["Полное название"]) if "Полное название" in it else cur["full_name"]
        if (name, full) != (cur["name"], cur["full_name"]):
            connection.execute("UPDATE ref_buildings SET name = ?, full_name = ? WHERE id = ?", (name, full, bid))
            updated["buildings"] += 1

    def floor(bcode: str, fcode: str) -> int:
        bid = building(bcode)
        for r in connection.execute("SELECT id, code FROM ref_floors WHERE building_id = ?", (bid,)):
            if rs._key(r["code"]) == rs._key(fcode):
                return r["id"]
        added["floors"] += 1
        return rs.add_floor(connection, bid, fcode, "", "")

    for it in f_rows:
        b, f = _s(it.get("building_code")), _s(it.get("floor_code"))
        if not b or not f:
            continue
        fid = floor(b, f)
        cur = connection.execute("SELECT name, ground, note FROM ref_floors WHERE id = ?", (fid,)).fetchone()
        name = _s(it["floor_name"]) if "floor_name" in it else cur["name"]
        raw = _s(it.get("Наземный/подземный"))
        ground = _ground_in(raw) if "Наземный/подземный" in it else cur["ground"]
        note = _s(it["Примечание"]) if "Примечание" in it else cur["note"]
        if ground is None:  # непонятный текст: признак не меняем, текст уходит в примечание
            ground, note = cur["ground"], note or raw
        if (name, ground, note) != (cur["name"], cur["ground"], cur["note"]):
            connection.execute("UPDATE ref_floors SET name = ?, ground = ?, note = ? WHERE id = ?",
                               (name, ground, note, fid))
            updated["floors"] += 1

    for it in r_rows:
        b, f, r = _s(it.get("building_code")), _s(it.get("floor_code")), _s(it.get("room_code"))
        if not b or not f or not r:
            continue
        fid = floor(b, f)
        row = None
        for x in connection.execute("SELECT * FROM ref_rooms WHERE floor_id = ?", (fid,)):
            if rs._key(x["code"]) == rs._key(r):
                row = x
                break
        area = rs._area(it.get("Площадь_м2")) if "Площадь_м2" in it else None
        raw = _s(it.get("Наземный/подземный"))
        ground = _ground_in(raw) if "Наземный/подземный" in it else None
        if row is None:
            added["rooms"] += 1
            rs.add_room(connection, fid, r, _s(it.get("room_name")), ground or "", area)
            continue
        name = _s(it["room_name"]) if "room_name" in it else row["name"]
        if ground is None:
            ground = row["ground"]
        new_area = area if "Площадь_м2" in it else row["area"]
        if (name, ground, new_area) != (row["name"], row["ground"], row["area"]):
            connection.execute("UPDATE ref_rooms SET name = ?, ground = ?, area = ? WHERE id = ?",
                               (name, ground, new_area, row["id"]))
            updated["rooms"] += 1
    connection.commit()
    return {"added": added, "updated": updated, "skipped": skipped}
