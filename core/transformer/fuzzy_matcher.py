"""Сопоставление заголовков с каноническими именами (ТЗ Этапа 2, п. 2.2-2.3).

Пока реализован только точный поиск через справочник `header_synonyms`:
найденный заголовок получает оценку 100. Нечёткий поиск (rapidfuzz) идёт
следующим коммитом.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from core import database

EXACT_SCORE = 100.0


def find_exact_match(connection: sqlite3.Connection, header: str) -> dict[str, Any] | None:
    """Точное совпадение заголовка со справочником синонимов.

    Принимает сырой или уже нормализованный заголовок. Возвращает запись
    отчёта (формат п. 2.3) или None, если заголовка в справочнике нет.
    """
    canonical = database.get_canonical_for_synonym(connection, header)
    if canonical is None:
        return None
    return {
        "source_header": header,
        "suggested_canonical": canonical,
        "score": EXACT_SCORE,
        "is_exact_match": True,
        "requires_manual_review": False,
    }
