"""Сопоставление заголовков с каноническими именами (ТЗ Этапа 2, п. 2.2-2.3).

Точный поиск через справочник `header_synonyms` даёт оценку 100, нечёткий
(rapidfuzz, `token_sort_ratio`, порог 85) подбирает ближайшее имя.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from rapidfuzz import fuzz, process

from core import database

EXACT_SCORE = 100.0
MATCH_THRESHOLD = 85.0
ABBREVIATION_SCORE = 90.0

_HYPHEN_RE = re.compile(r"[-–—]")
# Обе части не короче 2 букв: «р-н», «в-во» не подходят.
_ABBREVIATION_RE = re.compile(r"([а-яёa-z]{2,})[-–—]([а-яёa-z]{2,})")


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
    if score < threshold:
        canonical = _abbreviation_match(header, rows)
        if canonical is not None:
            result["suggested_canonical"] = canonical
            result["score"] = ABBREVIATION_SCORE
            result["requires_manual_review"] = False
            result["method"] = "abbreviation"
    return result


def _abbreviation_match(header: str, rows: list[sqlite3.Row]) -> str | None:
    """Сокращение с дефисом («кол-во» -> «количество»).

    Часть до дефиса должна быть началом слова, часть после - его концом, а
    слово - длиннее сокращения. Применяется к исходной строке: при
    нормализации дефис пропадает. Каноническое имя возвращается, только если
    подходящие синонимы указывают на одно и то же имя.
    """
    tokens = str(header or "").casefold().replace(".", "").split()
    if not any(_HYPHEN_RE.search(t) for t in tokens):
        return None
    parts: list[str] = []
    for token in tokens:
        found = _ABBREVIATION_RE.fullmatch(token)
        if found:
            parts.append(re.escape(found[1]) + ".{2,}" + re.escape(found[2]))
        elif _HYPHEN_RE.search(token):
            return None
        else:
            parts.append(re.escape(database.synonym_key(token)))
    pattern = re.compile("".join(parts))
    names = {
        row["canonical_name"]
        for row in rows
        if pattern.fullmatch(row["synonym_normalized"])
    }
    return names.pop() if len(names) == 1 else None


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
