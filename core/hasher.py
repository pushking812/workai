"""Хэширование файлов и определение документа/версии (Этап 1.2).

Документ определяется штампом: шифр (`doc_code`), номер изменения
(`revision`) и дата изменения (`revision_date`). Хэш нужен только для
того, чтобы отличить тот же самый файл от второго варианта документа
с теми же реквизитами. Путь на версию не влияет.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from typing import Any

from core import database
from core.parsers.stamp_parser import parse_stamp

CHUNK_SIZE = 8192

RESULT_NEW = "NEW"
RESULT_NEW_VERSION = "NEW_VERSION"
RESULT_NEW_VARIANT = "NEW_VARIANT"
RESULT_ALREADY_EXISTS = "ALREADY_EXISTS"


def calculate_sha256(file_path: str) -> str:
    """Считает SHA-256 файла, читая его блоками, чтобы не есть память."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_variant_group(
    doc_code: str,
    revision: str,
    revision_date: str | None,
) -> str:
    """Хэш от реквизитов штампа: записи с одинаковым значением — варианты."""
    raw = "|".join(
        [
            (doc_code or "").strip().upper(),
            str(revision or "0").strip(),
            (revision_date or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalized_revision(value: Any) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if digits else "0"


def process_file_entry(
    file_path: str,
    connection: sqlite3.Connection,
    stamp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Определяет, что за файл перед нами, и при необходимости пишет его в БД.

    Возвращает словарь с результатом (`NEW`, `NEW_VERSION`, `NEW_VARIANT`,
    `ALREADY_EXISTS`), хэшем, путём и реквизитами штампа.
    """
    abs_path = os.path.abspath(file_path)
    file_hash = calculate_sha256(abs_path)
    stamp = stamp if stamp is not None else parse_stamp(abs_path)

    doc_code = (stamp.get("doc_code") or "").strip().upper()
    revision = _normalized_revision(stamp.get("revision"))
    revision_date = stamp.get("revision_date")

    result: dict[str, Any] = {
        "result": RESULT_NEW,
        "hash": file_hash,
        "path": abs_path,
        "doc_code": doc_code,
        "revision": revision,
        "revision_date": revision_date,
        "variant_group": None,
        "is_current": 1,
        "file_id": None,
    }

    # Тот же файл по тому же пути уже в БД (даже если реквизиты штампа
    # при повторном разборе вышли другими) — дубль не создаём.
    same_file = database.get_by_hash_and_path(connection, file_hash, abs_path)
    if same_file:
        result.update(
            {
                "result": RESULT_ALREADY_EXISTS,
                "file_id": same_file["id"],
                "variant_group": same_file.get("variant_group"),
                "is_current": same_file.get("is_current", 1),
            }
        )
        return result

    # Без шифра документ нельзя сопоставить с другими — храним отдельной
    # записью, но повторный прогон того же файла дубля не создаёт.
    if not doc_code:
        existing = database.get_current_by_path(connection, abs_path)
        if existing and existing["hash"] == file_hash:
            result.update({"file_id": existing["id"], "result": RESULT_ALREADY_EXISTS})
            return result
        file_id = database.add_file(
            connection,
            file_hash=file_hash,
            path=abs_path,
            filename=os.path.basename(abs_path),
            stamp=stamp,
        )
        result.update({"file_id": file_id, "result": RESULT_NEW})
        return result

    variant_group = compute_variant_group(doc_code, revision, revision_date)
    result["variant_group"] = variant_group

    same_group = database.get_by_variant_group(connection, variant_group)
    if same_group:
        if any(item["hash"] == file_hash for item in same_group):
            result.update(
                {
                    "result": RESULT_ALREADY_EXISTS,
                    "file_id": same_group[0]["id"],
                }
            )
            return result
        # Те же шифр/изм./дата, но другое содержимое — вариант для пользователя.
        file_id = database.add_file(
            connection,
            file_hash=file_hash,
            path=abs_path,
            filename=os.path.basename(abs_path),
            stamp=stamp,
            variant_group=variant_group,
        )
        database.recalc_is_current(connection, doc_code)
        result.update({"result": RESULT_NEW_VARIANT, "file_id": file_id})
        return result

    has_versions = bool(database.get_by_doc_code(connection, doc_code))
    file_id = database.add_file(
        connection,
        file_hash=file_hash,
        path=abs_path,
        filename=os.path.basename(abs_path),
        stamp=stamp,
        variant_group=variant_group,
    )
    database.recalc_is_current(connection, doc_code)
    recorded = database.get_file_by_id(connection, file_id) or {}
    result.update(
        {
            "result": RESULT_NEW_VERSION if has_versions else RESULT_NEW,
            "file_id": file_id,
            "is_current": recorded.get("is_current", 1),
        }
    )
    return result
