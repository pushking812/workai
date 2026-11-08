"""Сопоставление заголовков с каноническими именами (ТЗ Этапа 2, п. 2.2-2.3).

Точный поиск через справочник `header_synonyms` даёт оценку 100, нечёткий
(rapidfuzz, `token_sort_ratio`, порог 85) подбирает ближайшее имя.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from rapidfuzz import fuzz, process

from core import database

EXACT_SCORE = 100.0
MATCH_THRESHOLD = 85.0


def find_best_match(
    connection: sqlite3.Connection,
    header: str,
    threshold: float = MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Лучшее каноническое имя для заголовка (точно, затем нечётко).

    Сначала точный поиск по справочнику (оценка 100). Иначе заголовок
    сравнивается через `token_sort_ratio` со всеми синонимами справочника
    (в них входят и сами канонические имена). Оценка не ниже порога даёт
    совпадение; ниже порога лучший кандидат возвращается как подсказка с
    `requires_manual_review: True`. Если подсказки нет, `suggested_canonical`
    равен None.
    """
    exact = find_exact_match(connection, header)
    if exact is not None:
        return exact

    result: dict[str, Any] = {
        "source_header": header,
        "suggested_canonical": None,
        "score": 0.0,
        "is_exact_match": False,
        "requires_manual_review": True,
    }
    key = database.synonym_key(header)
    if not key:
        return result

    rows = connection.execute(
        "SELECT canonical_name, synonym_normalized FROM header_synonyms"
    ).fetchall()
    if not rows:
        return result
    keys = [row["synonym_normalized"] for row in rows]
    best = process.extractOne(key, keys, scorer=fuzz.token_sort_ratio)
    if best is None:
        return result
    _, score, index = best
    result["suggested_canonical"] = rows[index]["canonical_name"]
    result["score"] = round(float(score), 1)
    result["requires_manual_review"] = score < threshold
    return result


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
