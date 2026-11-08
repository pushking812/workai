"""Единый набор статусов файла (Этап 3.3).

В БД (`files.status`) хранятся только `FileStatus`. Статусы `FOUND`, `EXISTS`
и `VARIANTS` вычисляются в момент отрисовки таблицы и в БД не пишутся.
"""

from __future__ import annotations

from enum import Enum


class FileStatus(str, Enum):
    SAVED = "SAVED"
    PROCESSING = "PROCESSING"
    NEEDS_MAPPING = "NEEDS_MAPPING"
    READY = "READY"
    ERROR = "ERROR"
    HIDDEN = "HIDDEN"


class UiStatus(str, Enum):
    """Статусы только для интерфейса."""

    FOUND = "FOUND"
    EXISTS = "EXISTS"
    VARIANTS = "VARIANTS"


DB_STATUSES = tuple(status.value for status in FileStatus)


def is_db_status(value: str) -> bool:
    return value in DB_STATUSES
