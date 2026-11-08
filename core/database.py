"""Работа с SQLite: схема таблицы `files` и функции доступа к данным.

Документ идентифицируется реквизитами штампа (doc_code, revision,
revision_date), а не путём к файлу. Путь хранится как вспомогательная
информация для решения пользователя.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable

DB_PATH = os.path.join("data", "app.db")
SCHEMA_VERSION = 7
# Версия, добавившая блок «Маркировка кабелей» (V7_KZH_NAMES).
SYNONYMS_V7_VERSION = 7
# Версия, добавившая блок «Проход через» (V6_KZH_NAMES).
SYNONYMS_V6_VERSION = 6
# Версия схемы, в которой справочник синонимов заполняется базовым набором.
SYNONYMS_SEED_VERSION = 3
# Версия, добавившая ФормулаРасчета и NЛСР и убравшая «примечание» из ссылки.
SYNONYMS_V4_VERSION = 4
# Версия, добавившая канонические имена КЖ (KZH_SYNONYMS).
SYNONYMS_V5_VERSION = 5

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

CREATE_SCHEMAS_TABLE = """
CREATE TABLE IF NOT EXISTS schemas (
    schema_hash             TEXT PRIMARY KEY,
    raw_headers_json        TEXT NOT NULL,
    normalized_headers_json TEXT NOT NULL,
    mapping_json            TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SYNONYMS_TABLE = """
CREATE TABLE IF NOT EXISTS header_synonyms (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name      TEXT NOT NULL,
    synonym_normalized  TEXT NOT NULL UNIQUE,
    confidence_score    REAL NOT NULL DEFAULT 1.0
)
"""

# Базовый справочник (ТЗ Этапа 2, п. 2.2): каноническое имя -> синонимы в
# «человеческом» виде. При записи они приводятся к `normalize_header(...).casefold()`,
# так что «ед изм» и «Ед. изм.» дают один ключ `едизм`. Каноническое имя
# синонимом самого себя добавляется автоматически.
SEED_SYNONYMS: dict[str, tuple[str, ...]] = {
    "NПП": ("nпп", "n п/п", "№ п/п", "номер", "n", "№"),
    "НаименованиеРабот": (
        "наименование работ",
        "наименование",
        "описание",
        "описание работ",
        "вид работ",
    ),
    "ЕдИзм": ("ед изм", "единица измерения", "ед", "единица"),
    "КолВо": ("кол во", "количество", "объем", "обьем"),
    "СсылкаНаЧерСпе": (
        "ссылка",
        "ссылка на чертежи",
        "ссылка на чертежи, спецификации",
    ),
    # Добавлено в версии 4 (колонки ВОР, не находившиеся в справочнике).
    "ФормулаРасчета": (
        "формула расчета",
        "формула расчета, расчет объемов работ и расхода материалов",
        "расчет объемов работ",
    ),
    "NЛСР": ("№ в лср", "№ лср", "номер в лср", "n в лср"),
}

# Колонки КЖ (кабельный журнал), версия 5. Канонические имена — иерархические
# заголовки так, как их отдаёт парсер (kzh_heaaders.xlsx + «Участок трассы кабеля»).
# Блок «Проложен» не выгружается, поэтому в справочнике его нет. Короткие
# варианты (`ПоПроекту|Марка`) дают профили cable_section/pipes — это та же колонка.
KZH_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ОбозначениеКабеляПро": ("обозначение кабеля, провода", "обозначение кабеля"),
    "Трасса|Начало": ("трасса начало",),
    "Трасса|Конец": ("трасса конец",),
    "КабельПровод|ПоПроекту|Марка": (
        "кабель, провод|по проекту|марка",
        "по проекту|марка",
    ),
    "КабельПровод|ПоПроекту|КолЧислоИСечЖил": (
        "кабель, провод|по проекту|кол, число и сечение жил",
        "по проекту|кол, число и сечение жил",
        "ПоПроекту|КолЧислоИСечЖил",
    ),
    "КабельПровод|ПоПроекту|ДлинаМ": (
        "кабель, провод|по проекту|длина, м",
        "по проекту|длина, м",
    ),
    "УчастокТрассыКаб": ("участок трассы кабеля",),
    # Версия 6: блок «Проход через» из обновлённого kzh_heaaders.xlsx.
    "ПроходЧерез|Трубу|Обозначение": ("проход через трубу обозначение",),
    "ПроходЧерез|Трубу|ДиамПоСтаМм": (
        "проход через трубу диам по стандарту, мм",
        "проход через трубу диам. по стандарту, мм",
    ),
    "ПроходЧерез|Трубу|ДлинаМ": ("проход через трубу длина м",),
    "ПроходЧерез|ПротяжЯщикN": ("проход через протяж ящик, №",),
    # Версия 7: блок «Маркировка кабелей» (бирки).
    "NКабеляИЦвеБир": (
        "№ кабеля и цвет бирки",
        "маркировка кабелей № кабеля и цвет бирки",
    ),
    "МаркировкаКабелей|СторонаБирки|Лицевая": (
        "маркировка кабелей сторона бирки лицевая",
    ),
    "МаркировкаКабелей|СторонаБирки|Оборотная": (
        "маркировка кабелей сторона бирки оборотная",
    ),
}

V7_KZH_NAMES: tuple[str, ...] = (
    "NКабеляИЦвеБир",
    "МаркировкаКабелей|СторонаБирки|Лицевая",
    "МаркировкаКабелей|СторонаБирки|Оборотная",
)

V6_KZH_NAMES: tuple[str, ...] = (
    "ПроходЧерез|Трубу|Обозначение",
    "ПроходЧерез|Трубу|ДиамПоСтаМм",
    "ПроходЧерез|Трубу|ДлинаМ",
    "ПроходЧерез|ПротяжЯщикN",
)

# Что миграция на версию 4 вносит в уже существующие БД версии 3.
V4_NEW_SYNONYMS: dict[str, tuple[str, ...]] = {
    name: SEED_SYNONYMS[name] for name in ("ФормулаРасчета", "NЛСР")
}
# «Примечание» относили к ссылке на чертежи по ошибке — убираем.
V4_REMOVED_SYNONYMS: tuple[tuple[str, str], ...] = (("СсылкаНаЧерСпе", "примечание"),)

CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_files_schema_hash ON files(schema_hash)",
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
    """Создаёт таблицы files и schemas и индексы, если их ещё нет."""
    connection = get_connection(db_path)
    connection.execute(CREATE_FILES_TABLE)
    connection.execute(CREATE_SCHEMAS_TABLE)
    connection.execute(CREATE_SYNONYMS_TABLE)
    # БД, созданные до Этапа 2, могут не иметь колонки schema_hash.
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
    if "schema_hash" not in existing:
        connection.execute("ALTER TABLE files ADD COLUMN schema_hash TEXT")
    for statement in CREATE_INDEXES:
        connection.execute(statement)
    previous_version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    # Базовый справочник заполняется один раз — при миграции на версию 3,
    # чтобы удалённые пользователем синонимы не возвращались.
    if previous_version < SYNONYMS_SEED_VERSION:
        seed_dictionary(connection)
    else:
        if previous_version < SYNONYMS_V4_VERSION:
            migrate_synonyms_v4(connection)
        if previous_version < SYNONYMS_V5_VERSION:
            migrate_synonyms_v5(connection)
        if previous_version < SYNONYMS_V6_VERSION:
            migrate_synonyms_v6(connection)
        if previous_version < SYNONYMS_V7_VERSION:
            migrate_synonyms_v7(connection)
    return connection


def migrate_synonyms_v5(connection: sqlite3.Connection) -> None:
    """БД версии 4 -> 5: канонические имена КЖ. Существующие записи не меняются."""
    for canonical, synonyms in KZH_SYNONYMS.items():
        if canonical in V6_KZH_NAMES or canonical in V7_KZH_NAMES:
            continue
        for synonym in (canonical, *synonyms):
            add_synonym(connection, canonical, synonym, 1.0)


def migrate_synonyms_v6(connection: sqlite3.Connection) -> None:
    """БД версии 5 -> 6: блок «Проход через». Существующие записи не меняются."""
    for canonical in V6_KZH_NAMES:
        for synonym in (canonical, *KZH_SYNONYMS[canonical]):
            add_synonym(connection, canonical, synonym, 1.0)


def migrate_synonyms_v7(connection: sqlite3.Connection) -> None:
    """БД версии 6 -> 7: блок «Маркировка кабелей». Существующие записи не меняются."""
    for canonical in V7_KZH_NAMES:
        for synonym in (canonical, *KZH_SYNONYMS[canonical]):
            add_synonym(connection, canonical, synonym, 1.0)


def migrate_synonyms_v4(connection: sqlite3.Connection) -> None:
    """БД версии 3 -> 4: новые канонические имена и удаление «примечание».

    Удаляется только запись, которая всё ещё указывает на СсылкаНаЧерСпе:
    если пользователь перенёс синоним на другое имя, он остаётся.
    """
    for canonical, synonyms in V4_NEW_SYNONYMS.items():
        for synonym in (canonical, *synonyms):
            add_synonym(connection, canonical, synonym, 1.0)
    for canonical, synonym in V4_REMOVED_SYNONYMS:
        connection.execute(
            "DELETE FROM header_synonyms WHERE canonical_name = ? AND synonym_normalized = ?",
            (canonical, synonym_key(synonym)),
        )
    connection.commit()


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


def get_by_hash_and_path(
    connection: sqlite3.Connection, file_hash: str, path: str
) -> dict[str, Any] | None:
    """Запись с точно такими же хэшем и путём (ограничение UNIQUE(hash, path))."""
    cursor = connection.execute(
        "SELECT * FROM files WHERE hash = ? AND path = ? ORDER BY id DESC LIMIT 1",
        (file_hash, path),
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


def save_schema(
    connection: sqlite3.Connection,
    schema_hash: str,
    raw_headers: list[str],
    normalized_headers: list[str],
) -> bool:
    """Сохраняет схему таблицы. Возвращает True, если схема новая.

    Существующую схему не перезаписываем: в ней может лежать `mapping_json`.
    """
    cursor = connection.execute(
        "INSERT OR IGNORE INTO schemas "
        "(schema_hash, raw_headers_json, normalized_headers_json) VALUES (?, ?, ?)",
        (
            schema_hash,
            json.dumps(raw_headers, ensure_ascii=False),
            json.dumps(normalized_headers, ensure_ascii=False),
        ),
    )
    connection.commit()
    return cursor.rowcount > 0


def get_schema(connection: sqlite3.Connection, schema_hash: str) -> dict[str, Any] | None:
    """Схема с распарсенными JSON-полями или None."""
    row = connection.execute(
        "SELECT * FROM schemas WHERE schema_hash = ?", (schema_hash,)
    ).fetchone()
    if row is None:
        return None
    schema = dict(row)
    schema["raw_headers"] = json.loads(schema.pop("raw_headers_json"))
    schema["normalized_headers"] = json.loads(schema.pop("normalized_headers_json"))
    mapping = schema.pop("mapping_json")
    schema["mapping"] = json.loads(mapping) if mapping else None
    return schema


def set_schema_mapping(
    connection: sqlite3.Connection, schema_hash: str, mapping: dict[str, Any]
) -> None:
    """Записывает итоговое сопоставление заголовков схемы."""
    connection.execute(
        "UPDATE schemas SET mapping_json = ? WHERE schema_hash = ?",
        (json.dumps(mapping, ensure_ascii=False), schema_hash),
    )
    connection.commit()


def set_file_schema_hash(
    connection: sqlite3.Connection, file_id: int, schema_hash: str | None
) -> None:
    """Привязывает запись файла к схеме его таблицы."""
    connection.execute(
        "UPDATE files SET schema_hash = ? WHERE id = ?", (schema_hash, file_id)
    )
    connection.commit()


def set_schema_hash_for_file_hash(
    connection: sqlite3.Connection, file_hash: str, schema_hash: str
) -> None:
    """Привязывает схему ко всем записям с этим хэшем содержимого."""
    connection.execute(
        "UPDATE files SET schema_hash = ? WHERE hash = ?", (schema_hash, file_hash)
    )
    connection.commit()


def synonym_key(text: object) -> str:
    """Ключ поиска в справочнике: `normalize_header(text).casefold()`."""
    from core.transformer.schema_analyzer import normalize_header

    return normalize_header(text).casefold()


def add_synonym(
    connection: sqlite3.Connection,
    canonical_name: str,
    synonym: str,
    confidence: float = 1.0,
) -> bool:
    """Добавляет синоним (любой текст, нормализуется сам).

    Существующий синоним не меняется: возвращает False, если ключ уже занят.
    """
    key = synonym_key(synonym)
    if not key:
        return False
    cursor = connection.execute(
        "INSERT OR IGNORE INTO header_synonyms "
        "(canonical_name, synonym_normalized, confidence_score) VALUES (?, ?, ?)",
        (canonical_name, key, confidence),
    )
    connection.commit()
    return cursor.rowcount > 0


def seed_dictionary(connection: sqlite3.Connection) -> int:
    """Заполняет справочник базовыми значениями. Возвращает число новых записей.

    Идемпотентна и ничего не перезаписывает: ручные синонимы сохраняются.
    """
    added = 0
    for canonical, synonyms in {**SEED_SYNONYMS, **KZH_SYNONYMS}.items():
        for synonym in (canonical, *synonyms):
            added += add_synonym(connection, canonical, synonym, 1.0)
    return added


def get_canonical_for_synonym(
    connection: sqlite3.Connection, normalized_header: str
) -> str | None:
    """Каноническое имя для заголовка или None, если его нет в справочнике.

    Принимает как уже нормализованный заголовок, так и сырой текст.
    """
    key = synonym_key(normalized_header)
    if not key:
        return None
    row = connection.execute(
        "SELECT canonical_name FROM header_synonyms WHERE synonym_normalized = ?",
        (key,),
    ).fetchone()
    return row["canonical_name"] if row else None


def get_files_by_schema(connection: sqlite3.Connection, schema_hash: str) -> list[dict[str, Any]]:
    """Все файлы с одинаковой структурой таблицы."""
    cursor = connection.execute(
        "SELECT * FROM files WHERE schema_hash = ? ORDER BY id", (schema_hash,)
    )
    return [dict(row) for row in cursor.fetchall()]


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
