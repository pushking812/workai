"""Нормализация заголовков (ТЗ Этапа 2, п. 2.1).

Пока реализована только `normalize_header`: она нужна парсеру DOCX, чтобы
привести уровни многоуровневой шапки к одному виду перед склейкой через `|`.
Остальное (schema_hash, таблица `schemas`) появится на Этапе 2.
"""

from __future__ import annotations

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
