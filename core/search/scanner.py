"""Рекурсивный поиск документов Word по маске (Этап 3.1)."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Callable, Iterable, Iterator

DEFAULT_EXTENSIONS = (".docx", ".doc")


_LATIN_TO_CYRILLIC = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "k": "к", "m": "м", "h": "н", "b": "в", "t": "т",
})


def normalize_lookalikes(text: str) -> str:
    """Визуально одинаковые латинские буквы -> кириллица (`Cпецификация` = `Спецификация`)."""
    return (text or "").translate(_LATIN_TO_CYRILLIC)


def _words_regex(name_words: Iterable[str] | None) -> "re.Pattern[str] | None":
    """Регэксп «слово целиком»: рядом с совпадением нет буквы (цифры и знаки можно).

    Так `СО` не находится в `СОС`, `СОУЭ`, `КСОБ`, `Содержание`, а `СВОР1` и `.ВОР` находятся.
    """
    words = sorted({normalize_lookalikes(w.strip()) for w in (name_words or ()) if w and w.strip()}, key=len, reverse=True)
    if not words:
        return None
    body = "|".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![^\W\d_])(?:{body})(?![^\W\d_])", re.IGNORECASE)


def _folder_key(text: str) -> str:
    """Имя папки для сравнения: без пробелов и регистра (`Ред. формат` = `Ред.формат`)."""
    return normalize_lookalikes("".join(text.split())).casefold()


def folder_matcher(folder_filters: Iterable[str] | None) -> "Callable[[str], bool] | None":
    """Проверка имени вложенной папки: имя должно НАЧИНАТЬСЯ с одной из подстрок; None, если фильтра нет."""
    keys = [k for k in (_folder_key(f) for f in (folder_filters or ())) if k]
    if not keys:
        return None
    return lambda name: any(_folder_key(name).startswith(k) for k in keys)


def scan_files(
    directories: Iterable[str],
    mask: str = "*",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    should_stop: Callable[[], bool] | None = None,
    name_words: Iterable[str] | None = None,
    folder_filters: Iterable[str] | None = None,
) -> Iterator[str]:
    """Генератор путей документов, имя которых подходит под маску.

    Пропускаются скрытые папки (начинаются с `.`) и временные файлы Word
    (`~$…`). Маска без учёта регистра; расширение проверяется отдельно.
    `should_stop` проверяется перед каждой папкой и файлом.
    `name_words`: если задан непустой набор, файл берётся, только когда его имя
    содержит хотя бы одно слово целиком, то есть без букв вплотную (без учёта регистра); остальные
    отбрасываются сразу, до любой другой обработки.
    `folder_filters`: если задан непустой список, сканер заходит только во вложенные
    папки, имя которых начинается с одной из подстрок (без учёта регистра и пробелов).
    Это правило действует на каждом уровне вложенности; файлы прямо в начальной
    папке берутся всегда, сама начальная папка фильтром не проверяется.
    """
    mask = (mask or "*").lower()
    word_re = _words_regex(name_words)
    folder_ok = folder_matcher(folder_filters)
    seen: set[str] = set()
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, dirs, files in os.walk(directory):
            if should_stop and should_stop():
                return
            dirs[:] = sorted(
                name for name in dirs
                if not name.startswith(".") and (folder_ok is None or folder_ok(name))
            )
            for name in sorted(files):
                if should_stop and should_stop():
                    return
                if name.startswith("~$") or name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() not in extensions:
                    continue
                lowered = name.lower()
                if word_re is not None and not word_re.search(normalize_lookalikes(name)):
                    continue
                if not fnmatch.fnmatch(lowered, mask):
                    continue
                path = os.path.join(root, name)
                key = os.path.normcase(os.path.abspath(path))
                if key in seen:
                    continue
                seen.add(key)
                yield path
