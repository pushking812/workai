"""Работа с SQLite: схема таблицы `files` и функции доступа к данным.

Документ идентифицируется реквизитами штампа (doc_code, revision,
revision_date), а не путём к файлу. Путь хранится как вспомогательная
информация для решения пользователя.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable

DB_PATH = os.path.join("data", "app.db")
SCHEMA_VERSION = 1

CREATE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    NOT NULL,
    path            TEXT    NOT NULL,
    filename        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'SAVED',
    error_message   TEXT,
    doc_code        TEXT,
    project_code    TEXT,
    section_code    TEXT,
    doc_type        TEXT,
    revision        TEXT    NOT NULL DEFAULT '0',
    revision_date   TEXT,
    sheet           INTEGER,
    sheets_total    INTEGER,
    stamp_raw       TEXT,
    stamp_status    TEXT    NOT NULL DEFAULT 'OK',
    variant_group   TEXT,
    is_current      INTEGER NOT NULL DEFAULT 1,
    schema_hash     TEXT,
    csv_path        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hash, path)
)
"""

CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_files_doc_code ON files(doc_code)",
    "CREATE INDEX IF NOT EXISTS idx_files_variant_group ON files(variant_group)",
    "CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)",
    "CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)",
)

FILES_COLUMNS = (
    "id",
    "hash",
    "path",
    "filename",
    "status",
    "error_message",
    "doc_code",
    "project_code",
    "section_code",
    "doc_type",
    "revision",
    "revision_date",
    "sheet",
    "sheets_total",
    "stamp_raw",
    "stamp_status",
    "variant_group",
    "is_current",
    "schema_hash",
    "csv_path",
    "created_at",
)

# Поля, которые приходят из парсера штампа (п. 1.4 ТЗ).
STAMP_FIELDS = (
    "doc_code",
    "project_code",
    "section_code",
    "doc_type",
    "revision",
    "revision_date",
    "sheet",
    "sheets_total",
    "stamp_raw",
    "stamp_status",
)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Открывает соединение с БД. Путь по умолчанию — data/app.db."""
    path = db_path or DB_PATH
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Создаёт таблицу files и индексы, если их ещё нет."""
    connection = get_connection(db_path)
    connection.execute(CREATE_FILES_TABLE)
    for statement in CREATE_INDEXES:
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_file_by_id(connection: sqlite3.Connection, file_id: int) -> dict[str, Any] | None:
    cursor = connection.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    return row_to_dict(cursor.fetchone())


def get_current_by_path(connection: sqlite3.Connection, path: str) -> dict[str, Any] | None:
    """Текущая запись по пути — используется, чтобы понять, менялся ли файл."""
    cursor = connection.execute(
        "SELECT * FROM files WHERE path = ? AND is_current = 1 ORDER BY id DESC LIMIT 1",
        (path,),
    )
    return row_to_dict(cursor.fetchone())


def get_by_variant_group(connection: sqlite3.Connection, variant_group: str) -> list[dict[str, Any]]:
    """Все записи с одинаковыми реквизитами штампа (шифр, изм., дата)."""
    cursor = connection.execute(
        "SELECT * FROM files WHERE variant_group = ? ORDER BY id",
        (variant_group,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_by_doc_code(connection: sqlite3.Connection, doc_code: str) -> list[dict[str, Any]]:
    """Все версии документа с указанным шифром."""
    cursor = connection.execute(
        "SELECT * FROM files WHERE doc_code = ? ORDER BY revision, revision_date, id",
        (doc_code,),
    )
    return [dict(row) for row in cursor.fetchall()]


def add_file(
    connection: sqlite3.Connection,
    file_hash: str,
    path: str,
    filename: str,
    stamp: dict[str, Any] | None = None,
    status: str = "SAVED",
    variant_group: str | None = None,
) -> int:
    """Добавляет запись о файле вместе с реквизитами штампа. Возвращает id."""
    stamp = stamp or {}
    values: dict[str, Any] = {
        "hash": file_hash,
        "path": path,
        "filename": filename,
        "status": status,
        "variant_group": variant_group,
    }
    for field in STAMP_FIELDS:
        if field in stamp:
            values[field] = stamp[field]

    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cursor = connection.execute(
        f"INSERT INTO files ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_file_status(
    connection: sqlite3.Connection,
    file_id: int,
    status: str,
    csv_path: str | None = None,
    error_message: str | None = None,
) -> None:
    """Обновляет статус записи, путь к CSV и текст ошибки."""
    connection.execute(
        "UPDATE files SET status = ?, csv_path = COALESCE(?, csv_path), "
        "error_message = ? WHERE id = ?",
        (status, csv_path, error_message, file_id),
    )
    connection.commit()


def update_file_stamp(
    connection: sqlite3.Connection,
    file_id: int,
    stamp: dict[str, Any],
) -> None:
    """Обновляет реквизиты штампа (например, после повторного разбора)."""
    fields: Iterable[str] = STAMP_FIELDS
    present = [field for field in fields if field in stamp]
    if not present:
        return
    assignments = ", ".join(f"{field} = ?" for field in present)
    params = [stamp[field] for field in present]
    params.append(file_id)
    connection.execute(f"UPDATE files SET {assignments} WHERE id = ?", tuple(params))
    connection.commit()


def _revision_key(row: dict[str, Any]) -> tuple[int, str]:
    """Ключ версии: числовой номер изменения и дата изменения."""
    raw = str(row.get("revision") or "0")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return (int(digits) if digits else 0, str(row.get("revision_date") or ""))


def recalc_is_current(connection: sqlite3.Connection, doc_code: str) -> list[int]:
    """Пересчитывает актуальность версий внутри документа.

    Текущими остаются записи с максимальным номером изменения и самой
    поздней датой изменения. Если у них совпадают реквизиты, но различается
    хэш, текущими остаются обе — это варианты, между которыми выбирает
    пользователь. Возвращает id текущих записей.
    """
    rows = get_by_doc_code(connection, doc_code)
    if not rows:
        return []

    best = max(_revision_key(row) for row in rows)
    current_ids = [row["id"] for row in rows if _revision_key(row) == best]

    for row in rows:
        target = 1 if row["id"] in current_ids else 0
        if row["is_current"] != target:
            connection.execute(
                "UPDATE files SET is_current = ? WHERE id = ?",
                (target, row["id"]),
            )
    connection.commit()
    return current_ids


def set_is_current(connection: sqlite3.Connection, file_id: int, value: int) -> None:
    """Прямое переключение флага актуальности (решение пользователя)."""
    connection.execute(
        "UPDATE files SET is_current = ? WHERE id = ?",
        (1 if value else 0, file_id),
    )
    connection.commit()


def list_files(
    connection: sqlite3.Connection,
    status: str | None = None,
    only_current: bool = False,
) -> list[dict[str, Any]]:
    """Список записей для UI."""
    query = "SELECT * FROM files"
    conditions: list[str] = []
    params: list[Any] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if only_current:
        conditions.append("is_current = 1")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY doc_code, revision, revision_date, id"
    cursor = connection.execute(query, tuple(params))
    return [dict(row) for row in cursor.fetchall()]
