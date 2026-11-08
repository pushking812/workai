"""Рекурсивный поиск документов Word по маске (Этап 3.1)."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable, Iterable, Iterator

DEFAULT_EXTENSIONS = (".docx", ".doc")


def scan_files(
    directories: Iterable[str],
    mask: str = "*",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[str]:
    """Генератор путей документов, имя которых подходит под маску.

    Пропускаются скрытые папки (начинаются с `.`) и временные файлы Word
    (`~$…`). Маска без учёта регистра; расширение проверяется отдельно.
    `should_stop` проверяется перед каждой папкой и файлом.
    """
    mask = (mask or "*").lower()
    seen: set[str] = set()
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, dirs, files in os.walk(directory):
            if should_stop and should_stop():
                return
            dirs[:] = sorted(name for name in dirs if not name.startswith("."))
            for name in sorted(files):
                if should_stop and should_stop():
                    return
                if name.startswith("~$") or name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() not in extensions:
                    continue
                if not fnmatch.fnmatch(name.lower(), mask):
                    continue
                path = os.path.join(root, name)
                key = os.path.normcase(os.path.abspath(path))
                if key in seen:
                    continue
                seen.add(key)
                yield path
