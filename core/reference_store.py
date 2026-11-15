"""Справочник зданий, этажей и помещений в БД приложения (редактируется в настройках).

Иерархия: здание -> этаж -> помещение. Связи хранятся по числовым id, поэтому
смена кода или названия не ломает связи внутри справочника. Если коды
справочника записаны текстом в других таблицах БД, такие места регистрируются
через `register_usage`: переименование обновляет их все, а удаление
используемого значения запрещено.

Первое наполнение — из `spravochniki.xlsx` (листы Здания, Этажи, Помещения),
один раз: удалённые пользователем значения потом не возвращаются.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import reference as reference_file

SEED_PATH = Path(__file__).resolve().parent.parent / "spravochniki.xlsx"
GROUND_VALUES = ("", "наземный", "подземный")
# Идентификатор uid задаётся при создании (префикс + номер записи), не меняется и не
# переиспользуется (AUTOINCREMENT); код остаётся коротким именем для показа.
UID_PREFIX = {"ref_buildings": "BLD", "ref_floors": "FLR", "ref_rooms": "ROM"}

_TABLES = (
    "CREATE TABLE IF NOT EXISTS ref_buildings ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,"
    "name TEXT NOT NULL DEFAULT '', full_name TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS ref_floors ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "building_id INTEGER NOT NULL REFERENCES ref_buildings(id),"
    "code TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',"
    "ground TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',"
    "UNIQUE (building_id, code))",
    "CREATE TABLE IF NOT EXISTS ref_rooms ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "floor_id INTEGER NOT NULL REFERENCES ref_floors(id),"
    "code TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',"
    "ground TEXT NOT NULL DEFAULT '', area REAL,"
    "UNIQUE (floor_id, code))",
    "CREATE TABLE IF NOT EXISTS ref_meta (key TEXT PRIMARY KEY, value TEXT)",
)


class ReferenceError_(Exception):
    """Понятная пользователю ошибка правки справочника."""


@dataclass(frozen=True)
class Usage:
    """Место в другой таблице БД, где записаны коды справочника текстом."""
    table: str
    building: str
    floor: str | None = None
    room: str | None = None
    title: str = ""


USAGES: list[Usage] = []


def register_usage(usage: Usage) -> None:
    if usage not in USAGES:
        USAGES.append(usage)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _key(code: str) -> str:
    return "".join(code.split()).casefold()


def ensure_tables(connection: sqlite3.Connection, seed: bool = True) -> None:
    for statement in _TABLES:
        connection.execute(statement)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(ref_rooms)")}
    if "area" not in columns:  # таблица создана до появления площади
        connection.execute("ALTER TABLE ref_rooms ADD COLUMN area REAL")
    for table, prefix in UID_PREFIX.items():
        cols = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "uid" not in cols:  # таблица создана до появления идентификатора
            connection.execute(f"ALTER TABLE {table} ADD COLUMN uid TEXT")
        connection.execute(
            f"UPDATE {table} SET uid = '{prefix}-' || printf('%06d', id) WHERE uid IS NULL OR uid = ''")
        connection.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_uid ON {table}(uid)")
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS tr_{table}_uid AFTER INSERT ON {table} "
            f"WHEN NEW.uid IS NULL OR NEW.uid = '' BEGIN "
            f"UPDATE {table} SET uid = '{prefix}-' || printf('%06d', NEW.id) WHERE id = NEW.id; END")
        connection.execute(  # uid неизменяем
            f"CREATE TRIGGER IF NOT EXISTS tr_{table}_uid_lock BEFORE UPDATE OF uid ON {table} "
            f"WHEN OLD.uid IS NOT NULL AND OLD.uid <> '' AND NEW.uid IS NOT OLD.uid "
            f"BEGIN SELECT RAISE(ABORT, 'uid не изменяется'); END")
    connection.commit()
    if seed:
        seed_from_file(connection)


def seed_from_file(connection: sqlite3.Connection, path: str | Path | None = None) -> bool:
    """Один раз переносит spravochniki.xlsx в БД. True — перенос выполнен."""
    done = connection.execute("SELECT 1 FROM ref_meta WHERE key = 'seeded'").fetchone()
    if done:
        return False
    path = Path(path or SEED_PATH)
    if not path.exists():
        return False
    import openpyxl

    ref = reference_file.load_reference(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        room_rows = []
        if "Помещения" in wb.sheetnames:
            for row in list(wb["Помещения"].iter_rows(values_only=True))[1:]:
                b, f, r = (_clean(row[i]) if len(row) > i else "" for i in range(3))
                if b and f and r:
                    room_rows.append((b, f, r, _area(row[5]) if len(row) > 5 else None))
    finally:
        wb.close()
    # «NONE / NONE / NONE — Не задано»: здание и этаж для него заводятся отдельно.
    for b, f, _r, _n in room_rows:
        ref.buildings.setdefault(b, {"name": "Не задано" if b == "NONE" else b, "full": ""})
        ref.floors.setdefault((b, f), {"name": "Не задано" if f == "NONE" else f, "ground_raw": ""})
    ids: dict[str, int] = {}
    for code, item in ref.buildings.items():
        connection.execute(
            "INSERT OR IGNORE INTO ref_buildings (code, name, full_name) VALUES (?, ?, ?)",
            (code, item["name"], item["full"]))
        ids[code] = connection.execute("SELECT id FROM ref_buildings WHERE code = ?", (code,)).fetchone()[0]
    floor_ids: dict[tuple[str, str], int] = {}
    for (b, f), item in ref.floors.items():
        connection.execute(
            "INSERT OR IGNORE INTO ref_floors (building_id, code, name, ground, note) VALUES (?, ?, ?, ?, ?)",
            (ids[b], f, item["name"], reference_file.ground_state(ref, b, f), item["ground_raw"]))
        floor_ids[(b, f)] = connection.execute(
            "SELECT id FROM ref_floors WHERE building_id = ? AND code = ?", (ids[b], f)).fetchone()[0]
    for b, f, r, area in room_rows:
        name = {"NONE": "Не задано"}.get(r)
        connection.execute(
            "INSERT OR IGNORE INTO ref_rooms (floor_id, code, name, ground, area) VALUES (?, ?, ?, '', ?)",
            (floor_ids[(b, f)], r, name or _room_name(path, b, f, r), area))
    connection.execute("INSERT OR REPLACE INTO ref_meta (key, value) VALUES ('seeded', '1')")
    connection.commit()
    return True


_room_names: dict[Path, dict[tuple[str, str, str], str]] = {}


def _room_name(path: Path, b: str, f: str, r: str) -> str:
    if path not in _room_names:
        import openpyxl

        names = {}
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if "Помещения" in wb.sheetnames:
                for row in list(wb["Помещения"].iter_rows(values_only=True))[1:]:
                    if len(row) > 3 and row[0] and row[1] and row[2]:
                        names[(_clean(row[0]), _clean(row[1]), _clean(row[2]))] = _clean(row[3])
        finally:
            wb.close()
        _room_names[path] = names
    return _room_names[path].get((b, f, r), "")


# ---------- чтение ----------

def _count_usage(connection: sqlite3.Connection, usage: Usage, b: str, f: str | None = None,
                 r: str | None = None) -> int:
    where, args = [f"{_q(usage.building)} = ?"], [b]
    if f is not None and usage.floor:
        where.append(f"{_q(usage.floor)} = ?")
        args.append(f)
    if r is not None and usage.room:
        where.append(f"{_q(usage.room)} = ?")
        args.append(r)
    try:
        return connection.execute(
            f"SELECT COUNT(*) FROM {_q(usage.table)} WHERE " + " AND ".join(where), args).fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # таблицы ещё нет — значит, и использований нет


def _external(connection: sqlite3.Connection, b: str, f: str | None = None, r: str | None = None) -> list[str]:
    """Где ещё используется значение: список «таблица: N»."""
    found = []
    for usage in USAGES:
        if f is not None and not usage.floor:
            continue
        if r is not None and not usage.room:
            continue
        n = _count_usage(connection, usage, b, f, r)
        if n:
            found.append(f"{usage.title or usage.table}: {n}")
    return found


def list_reference(connection: sqlite3.Connection) -> dict[str, Any]:
    ensure_tables(connection)
    buildings, floors, rooms = [], [], []
    bcode = {}
    for row in connection.execute("SELECT id, uid, code, name, full_name FROM ref_buildings ORDER BY id"):
        bcode[row["id"]] = row["code"]
        buildings.append({"id": row["id"], "uid": row["uid"], "code": row["code"], "name": row["name"],
                          "full": row["full_name"]})
    fcode = {}
    floor_rows = connection.execute(
        "SELECT id, uid, building_id, code, name, ground, note FROM ref_floors ORDER BY id").fetchall()
    room_rows = connection.execute(
        "SELECT id, uid, floor_id, code, name, ground, area FROM ref_rooms ORDER BY id").fetchall()
    per_floor: dict[int, int] = {}
    for row in room_rows:
        per_floor[row["floor_id"]] = per_floor.get(row["floor_id"], 0) + 1
    per_building: dict[int, int] = {}
    for row in floor_rows:
        per_building[row["building_id"]] = per_building.get(row["building_id"], 0) + 1
        fcode[row["id"]] = (row["building_id"], row["code"], row["ground"])
    for item in buildings:
        item["children"] = per_building.get(item["id"], 0)
        item["external"] = _external(connection, item["code"])
    for row in floor_rows:
        b = bcode[row["building_id"]]
        floors.append({"id": row["id"], "uid": row["uid"], "building_id": row["building_id"], "code": row["code"],
                       "name": row["name"], "ground": row["ground"], "note": row["note"],
                       "children": per_floor.get(row["id"], 0),
                       "external": _external(connection, b, row["code"])})
    for row in room_rows:
        building_id, floor_code, floor_ground = fcode[row["floor_id"]]
        rooms.append({"id": row["id"], "uid": row["uid"], "floor_id": row["floor_id"], "code": row["code"],
                      "name": row["name"], "ground": row["ground"], "area": row["area"],
                      "effective_ground": row["ground"] or floor_ground,
                      "external": _external(connection, bcode[building_id], floor_code, row["code"])})
    return {"buildings": buildings, "floors": floors, "rooms": rooms}


def to_reference(connection: sqlite3.Connection) -> reference_file.Reference:
    """Справочник в том виде, в котором его читает остальной код (`core.reference`)."""
    data = list_reference(connection)
    ref = reference_file.Reference()
    code = {b["id"]: b["code"] for b in data["buildings"]}
    for b in data["buildings"]:
        ref.buildings[b["code"]] = {"name": b["name"], "full": b["full"]}
    for f in data["floors"]:
        ref.floors[(code[f["building_id"]], f["code"])] = {"name": f["name"], "ground_raw": f["ground"]}
    return ref


# ---------- правка ----------

def _row(connection: sqlite3.Connection, table: str, item_id: Any):
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ReferenceError_("Элемент не найден: обновите окно.")
    return row


def _need_code(code: Any) -> str:
    code = _clean(code)
    if not code:
        raise ReferenceError_("Введите код.")
    return code


def _check_ground(value: Any) -> str:
    value = _clean(value).lower()
    if value not in GROUND_VALUES:
        raise ReferenceError_("Наземный/подземный: «наземный», «подземный» или пусто.")
    return value


def _area(value: Any) -> float | None:
    if value is None or _clean(value) == "":
        return None
    try:
        return round(float(str(value).replace(",", ".").replace(" ", "")), 2)
    except ValueError:
        return None


def _unique(connection: sqlite3.Connection, sql: str, args: tuple, code: str, what: str) -> None:
    for row in connection.execute(sql, args):
        if _key(row[0]) == _key(code):
            raise ReferenceError_(f"{what} с кодом «{row[0]}» уже есть.")


def _rename_external(connection: sqlite3.Connection, field: str, old_b: str, old_f: str | None,
                     old_r: str | None, new: str) -> None:
    """Переписывает код во всех зарегистрированных таблицах."""
    for usage in USAGES:
        col = getattr(usage, field)
        if not col:
            continue
        where, args = [f"{_q(usage.building)} = ?"], [old_b]
        if old_f is not None and usage.floor:
            where.append(f"{_q(usage.floor)} = ?")
            args.append(old_f)
        if old_r is not None and usage.room:
            where.append(f"{_q(usage.room)} = ?")
            args.append(old_r)
        try:
            connection.execute(
                f"UPDATE {_q(usage.table)} SET {_q(col)} = ? WHERE " + " AND ".join(where), [new, *args])
        except sqlite3.OperationalError:
            pass


def _refuse_if_used(what: str, children: int, children_name: str, external: list[str]) -> None:
    reasons = []
    if children:
        reasons.append(f"{children_name}: {children}")
    reasons.extend(external)
    if reasons:
        raise ReferenceError_(f"{what} используется, удалить нельзя ({'; '.join(reasons)}).")


def add_building(connection: sqlite3.Connection, code: Any, name: Any = "", full: Any = "") -> int:
    ensure_tables(connection)
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_buildings", (), code, "Здание")
    cur = connection.execute("INSERT INTO ref_buildings (code, name, full_name) VALUES (?, ?, ?)",
                             (code, _clean(name), _clean(full)))
    connection.commit()
    return cur.lastrowid


def update_building(connection: sqlite3.Connection, item_id: Any, code: Any, name: Any = None,
                    full: Any = "") -> None:
    """name=None — краткое название не трогаем (в окне его уже не правят)."""
    ensure_tables(connection)
    row = _row(connection, "ref_buildings", item_id)
    if name is None:
        name = row["name"]
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_buildings WHERE id <> ?", (item_id,), code, "Здание")
    if code != row["code"]:
        _rename_external(connection, "building", row["code"], None, None, code)
    connection.execute("UPDATE ref_buildings SET code = ?, name = ?, full_name = ? WHERE id = ?",
                       (code, _clean(name), _clean(full), item_id))
    connection.commit()


def delete_building(connection: sqlite3.Connection, item_id: Any) -> None:
    ensure_tables(connection)
    row = _row(connection, "ref_buildings", item_id)
    n = connection.execute("SELECT COUNT(*) FROM ref_floors WHERE building_id = ?", (item_id,)).fetchone()[0]
    _refuse_if_used(f"Здание «{row['code']}»", n, "этажей", _external(connection, row["code"]))
    connection.execute("DELETE FROM ref_buildings WHERE id = ?", (item_id,))
    connection.commit()


def add_floor(connection: sqlite3.Connection, building_id: Any, code: Any, name: Any = "",
              ground: Any = "") -> int:
    ensure_tables(connection)
    _row(connection, "ref_buildings", building_id)
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_floors WHERE building_id = ?", (building_id,), code, "Этаж")
    cur = connection.execute(
        "INSERT INTO ref_floors (building_id, code, name, ground) VALUES (?, ?, ?, ?)",
        (building_id, code, _clean(name), _check_ground(ground)))
    connection.commit()
    return cur.lastrowid


def update_floor(connection: sqlite3.Connection, item_id: Any, code: Any, name: Any = "",
                 ground: Any = "") -> None:
    ensure_tables(connection)
    row = _row(connection, "ref_floors", item_id)
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_floors WHERE building_id = ? AND id <> ?",
            (row["building_id"], item_id), code, "Этаж")
    if code != row["code"]:
        b = connection.execute("SELECT code FROM ref_buildings WHERE id = ?", (row["building_id"],)).fetchone()[0]
        _rename_external(connection, "floor", b, row["code"], None, code)
    connection.execute("UPDATE ref_floors SET code = ?, name = ?, ground = ? WHERE id = ?",
                       (code, _clean(name), _check_ground(ground), item_id))
    connection.commit()


def delete_floor(connection: sqlite3.Connection, item_id: Any) -> None:
    ensure_tables(connection)
    row = _row(connection, "ref_floors", item_id)
    b = connection.execute("SELECT code FROM ref_buildings WHERE id = ?", (row["building_id"],)).fetchone()[0]
    n = connection.execute("SELECT COUNT(*) FROM ref_rooms WHERE floor_id = ?", (item_id,)).fetchone()[0]
    _refuse_if_used(f"Этаж «{row['code']}»", n, "помещений", _external(connection, b, row["code"]))
    connection.execute("DELETE FROM ref_floors WHERE id = ?", (item_id,))
    connection.commit()


def add_room(connection: sqlite3.Connection, floor_id: Any, code: Any, name: Any = "",
             ground: Any = "", area: Any = None) -> int:
    ensure_tables(connection)
    _row(connection, "ref_floors", floor_id)
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_rooms WHERE floor_id = ?", (floor_id,), code, "Помещение")
    cur = connection.execute(
        "INSERT INTO ref_rooms (floor_id, code, name, ground, area) VALUES (?, ?, ?, ?, ?)",
        (floor_id, code, _clean(name), _check_ground(ground), _area(area)))
    connection.commit()
    return cur.lastrowid


def _room_path(connection: sqlite3.Connection, row) -> tuple[str, str]:
    f = connection.execute("SELECT building_id, code FROM ref_floors WHERE id = ?", (row["floor_id"],)).fetchone()
    b = connection.execute("SELECT code FROM ref_buildings WHERE id = ?", (f["building_id"],)).fetchone()[0]
    return b, f["code"]


def update_room(connection: sqlite3.Connection, item_id: Any, code: Any, name: Any = "",
                ground: Any = "") -> None:
    ensure_tables(connection)
    row = _row(connection, "ref_rooms", item_id)
    code = _need_code(code)
    _unique(connection, "SELECT code FROM ref_rooms WHERE floor_id = ? AND id <> ?",
            (row["floor_id"], item_id), code, "Помещение")
    if code != row["code"]:
        b, f = _room_path(connection, row)
        _rename_external(connection, "room", b, f, row["code"], code)
    connection.execute("UPDATE ref_rooms SET code = ?, name = ?, ground = ? WHERE id = ?",
                       (code, _clean(name), _check_ground(ground), item_id))
    connection.commit()


def delete_room(connection: sqlite3.Connection, item_id: Any) -> None:
    ensure_tables(connection)
    row = _row(connection, "ref_rooms", item_id)
    b, f = _room_path(connection, row)
    _refuse_if_used(f"Помещение «{row['code']}»", 0, "", _external(connection, b, f, row["code"]))
    connection.execute("DELETE FROM ref_rooms WHERE id = ?", (item_id,))
    connection.commit()
