"""Справочник заголовков: канонические имена, синонимы и игнорируемые заголовки.

Синонимы лежат в `header_synonyms` (ключ — `database.synonym_key`). Каноническое
имя существует, пока у него есть хотя бы один синоним (само имя тоже синоним).
Дополнительно:
- `user_roles` — канонические имена, заведённые пользователем (их нет в шаблоне
  книги; «Сформировать запросы» добавляет их столбцами в `СправочникКолонок`);
- `ignored_headers` — заголовки, которые пользователь решил игнорировать всегда.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from rapidfuzz import fuzz, process

from core import database

_TABLES = (
    "CREATE TABLE IF NOT EXISTS user_roles (name TEXT PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS ignored_headers ("
    "synonym_normalized TEXT PRIMARY KEY, raw TEXT NOT NULL)",
    # Исходное написание синонима (в header_synonyms хранится только ключ).
    "CREATE TABLE IF NOT EXISTS synonym_raw ("
    "synonym_normalized TEXT PRIMARY KEY, raw TEXT NOT NULL)",
)


def _remember_raw(connection: sqlite3.Connection, text: str) -> None:
    key = database.synonym_key(text)
    if key and _clean(text):
        connection.execute(
            "INSERT OR REPLACE INTO synonym_raw (synonym_normalized, raw) VALUES (?, ?)", (key, _clean(text))
        )


def _backfill_raw(connection: sqlite3.Connection) -> None:
    """Исходное написание синонимов начального словаря (для тех, что ещё не запомнены)."""
    for source in (database.SEED_SYNONYMS, database.KZH_SYNONYMS, database.SO_SYNONYMS):
        for canonical, synonyms in source.items():
            for text in (canonical, *synonyms):
                key = database.synonym_key(text)
                if key:
                    connection.execute(
                        "INSERT OR IGNORE INTO synonym_raw (synonym_normalized, raw) VALUES (?, ?)",
                        (key, _clean(text)),
                    )
    connection.commit()


class DictionaryError(Exception):
    pass


def ensure_tables(connection: sqlite3.Connection) -> None:
    for statement in _TABLES:
        connection.execute(statement)
    connection.commit()


def _clean(name: object) -> str:
    return " ".join(str(name or "").split())


def list_dictionary(connection: sqlite3.Connection) -> dict[str, Any]:
    """{"canonical": [{name, user_created, synonyms: [ключ]}], "ignored": [{key, raw}]}."""
    ensure_tables(connection)
    _backfill_raw(connection)
    labels = {r["synonym_normalized"]: r["raw"] for r in connection.execute("SELECT * FROM synonym_raw")}
    user = {r["name"] for r in connection.execute("SELECT name FROM user_roles")}
    grouped: dict[str, list[str]] = {}
    for row in connection.execute(
        "SELECT canonical_name, synonym_normalized FROM header_synonyms ORDER BY id"
    ):
        grouped.setdefault(row["canonical_name"], []).append(row["synonym_normalized"])
    # Само каноническое имя хранится как синоним, но в списке синонимов не показывается.
    shown = {
        name: [key for key in keys if key != database.synonym_key(name)]
        for name, keys in grouped.items()
    }
    canonical = [
        {"name": name, "user_created": name in user, "synonyms": shown[name],
         "labels": {key: labels.get(key, key) for key in shown[name]}}
        for name in sorted(grouped, key=str.casefold)
    ]
    ignored = [
        {"key": r["synonym_normalized"], "raw": r["raw"]}
        for r in connection.execute("SELECT synonym_normalized, raw FROM ignored_headers ORDER BY raw")
    ]
    return {"canonical": canonical, "ignored": ignored}


def user_roles(connection: sqlite3.Connection) -> list[str]:
    ensure_tables(connection)
    return [r["name"] for r in connection.execute("SELECT name FROM user_roles ORDER BY rowid")]


def ignored_keys(connection: sqlite3.Connection) -> set[str]:
    ensure_tables(connection)
    return {r["synonym_normalized"] for r in connection.execute("SELECT synonym_normalized FROM ignored_headers")}


def _exists(connection: sqlite3.Connection, canonical: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM header_synonyms WHERE canonical_name = ? LIMIT 1", (canonical,)
    ).fetchone() is not None


def add_canonical(connection: sqlite3.Connection, name: str, user_created: bool = True) -> str:
    """Новое каноническое имя (само имя становится синонимом)."""
    ensure_tables(connection)
    name = _clean(name)
    if not name:
        raise DictionaryError("Пустое имя")
    if _exists(connection, name):
        raise DictionaryError(f"Каноническое имя «{name}» уже есть")
    owner = database.get_canonical_for_synonym(connection, name)
    if owner:
        raise DictionaryError(f"«{name}» уже синоним имени «{owner}»")
    database.add_synonym(connection, name, name, 1.0)
    _remember_raw(connection, name)
    if user_created:
        connection.execute("INSERT OR IGNORE INTO user_roles (name) VALUES (?)", (name,))
        connection.commit()
    return name


def set_alias(connection: sqlite3.Connection, canonical: str, text: str) -> None:
    """Назначает синоним имени; если он был у другого имени — переносит."""
    ensure_tables(connection)
    key = database.synonym_key(text)
    if not key:
        raise DictionaryError("Пустой синоним")
    if not _exists(connection, canonical):
        raise DictionaryError(f"Нет канонического имени «{canonical}»")
    if not database.add_synonym(connection, canonical, text, 1.0):
        connection.execute(
            "UPDATE header_synonyms SET canonical_name = ? WHERE synonym_normalized = ?", (canonical, key)
        )
    _remember_raw(connection, text)
    # Назначенный заголовок больше не игнорируется.
    connection.execute("DELETE FROM ignored_headers WHERE synonym_normalized = ?", (key,))
    connection.commit()


def remove_alias(connection: sqlite3.Connection, key: str) -> None:
    """Удаляет синоним. Последний синоним имени не удаляется (имя пропало бы)."""
    row = connection.execute(
        "SELECT canonical_name FROM header_synonyms WHERE synonym_normalized = ?", (key,)
    ).fetchone()
    if row is None:
        return
    left = connection.execute(
        "SELECT COUNT(*) FROM header_synonyms WHERE canonical_name = ?", (row["canonical_name"],)
    ).fetchone()[0]
    if left <= 1:
        raise DictionaryError("Это последний синоним имени: удалите имя целиком")
    connection.execute("DELETE FROM header_synonyms WHERE synonym_normalized = ?", (key,))
    connection.commit()


def rename_alias(connection: sqlite3.Connection, key: str, canonical: str, text: str) -> None:
    """Меняет написание синонима: новый добавляется раньше, чем удаляется старый."""
    new_key = database.synonym_key(text)
    set_alias(connection, canonical, text)
    if new_key and new_key != key:
        remove_alias(connection, key)


def rename_ignored(connection: sqlite3.Connection, key: str, text: str) -> None:
    """Меняет написание игнорируемого заголовка."""
    new_key = database.synonym_key(text)
    if not new_key:
        raise DictionaryError("Пустой заголовок")
    if new_key != key:
        unignore_header(connection, key)
    ignore_header(connection, text)


def rename_canonical(connection: sqlite3.Connection, old: str, new: str) -> str:
    ensure_tables(connection)
    new = _clean(new)
    if not new:
        raise DictionaryError("Пустое имя")
    if new == old:
        return new
    if not _exists(connection, old):
        raise DictionaryError(f"Нет канонического имени «{old}»")
    if _exists(connection, new):
        raise DictionaryError(f"Каноническое имя «{new}» уже есть")
    connection.execute("UPDATE header_synonyms SET canonical_name = ? WHERE canonical_name = ?", (new, old))
    connection.execute("UPDATE user_roles SET name = ? WHERE name = ?", (new, old))
    connection.commit()
    return new


def delete_canonical(connection: sqlite3.Connection, name: str) -> int:
    """Удаляет имя и все его синонимы. Возвращает число удалённых синонимов."""
    ensure_tables(connection)
    cursor = connection.execute("DELETE FROM header_synonyms WHERE canonical_name = ?", (name,))
    connection.execute("DELETE FROM user_roles WHERE name = ?", (name,))
    connection.commit()
    return cursor.rowcount


def ignore_header(connection: sqlite3.Connection, text: str) -> None:
    ensure_tables(connection)
    key = database.synonym_key(text)
    if key:
        connection.execute(
            "INSERT OR REPLACE INTO ignored_headers (synonym_normalized, raw) VALUES (?, ?)",
            (key, _clean(text)),
        )
        connection.commit()


def unignore_header(connection: sqlite3.Connection, key: str) -> None:
    ensure_tables(connection)
    connection.execute("DELETE FROM ignored_headers WHERE synonym_normalized = ?", (key,))
    connection.commit()


def suggest(connection: sqlite3.Connection, header: str, allowed: list[str] | None = None,
            limit: int = 3) -> list[dict[str, Any]]:
    """Лучшие кандидаты (разные канонические имена) с оценкой схожести."""
    key = database.synonym_key(header)
    if not key:
        return []
    rows = connection.execute("SELECT canonical_name, synonym_normalized FROM header_synonyms").fetchall()
    if allowed is not None:
        rows = [r for r in rows if r["canonical_name"] in allowed]
    if not rows:
        return []
    found = process.extract(key, [r["synonym_normalized"] for r in rows], scorer=fuzz.token_sort_ratio,
                            limit=len(rows))
    result: dict[str, float] = {}
    for _text, score, index in found:
        result.setdefault(rows[index]["canonical_name"], round(float(score), 1))
        if len(result) >= limit:
            break
    return [{"canonical": name, "score": score} for name, score in result.items()]
