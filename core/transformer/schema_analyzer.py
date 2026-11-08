"""Нормализация заголовков (ТЗ Этапа 2, п. 2.1).

Пока реализована только `normalize_header`: она нужна парсеру DOCX, чтобы
привести уровни многоуровневой шапки к одному виду перед склейкой через `|`.
Остальное (schema_hash, таблица `schemas`) появится на Этапе 2.
"""

from __future__ import annotations

import hashlib
import re

MAX_HEADER_LENGTH = 15
KEPT_WORDS = 2
TRUNCATED_LENGTH = 3
_SEPARATORS_RE = re.compile(r"[\W_]+")


def normalize_header(text: object) -> str:
    """`"№ п/п"` -> `"NПП"`, `"Ед. изм."` -> `"ЕдИзм"`.

    * `ё` -> `е`, `№` -> `N`;
    * любые разделители (пробелы, точки, запятые, слэши, дефисы, скобки)
      убираются, слова склеиваются;
    * в каждом слове первая буква заглавная, остальные строчные;
    * если склеенная строка длиннее 15 символов, каждое слово начиная
      с третьего усекается до первых 3 символов
      (`"Формула расчета, расчет объемов работ"` -> `"ФормулаРасчетаРасОбъРаб"`).
    """
    if text is None:
        return ""
    value = str(text).replace("ё", "е").replace("Ё", "Е").replace("№", "N")
    words = [word for word in _SEPARATORS_RE.split(value) if word]
    words = [word[:1].upper() + word[1:].lower() for word in words]
    if len("".join(words)) > MAX_HEADER_LENGTH:
        words = [
            word if index < KEPT_WORDS else word[:TRUNCATED_LENGTH]
            for index, word in enumerate(words)
        ]
    return "".join(words)


SCHEMA_SEPARATOR = "|"


def generate_schema_hash(normalized_headers: list[str]) -> str:
    """MD5 от нормализованных заголовков в `casefold()`, склеенных через `|`.

    Входные заголовки нормализуются повторно: `normalize_header` идемпотентна
    для уже нормализованных строк, а сырые `"№ п/п"` и `"№п/п"` дают один хэш.
    """
    keys = [normalize_header(header).casefold() for header in normalized_headers]
    return hashlib.md5(SCHEMA_SEPARATOR.join(keys).encode("utf-8")).hexdigest()


def analyze_and_save_schema(connection, headers: list[str], file_hash: str) -> str | None:
    """Считает схему по шапке, сохраняет её и привязывает к файлам с этим хэшем.

    Возвращает `schema_hash` или None, если заголовков нет.
    """
    from core import database

    if not headers:
        return None
    normalized = [normalize_header(header) for header in headers]
    schema_hash = generate_schema_hash(normalized)
    database.save_schema(connection, schema_hash, list(headers), normalized)
    database.set_schema_hash_for_file_hash(connection, file_hash, schema_hash)
    return schema_hash
