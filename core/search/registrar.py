"""Привязка сканера к БД (Этап 3.4).

`FileRegistrar` — это `on_file` для `SearchManager`: для каждого найденного
файла читает штамп, применяет логику версий Этапа 1.2 (`process_file_entry`)
и запоминает UI-статус:

* новый документ или новая версия -> `FOUND` (в БД добавлен как `SAVED`);
* тот же файл уже в базе -> `EXISTS` (запись не меняется);
* те же шифр, изм. и дата, но другое содержимое -> `VARIANTS`.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from core import database
from core.doc_converter import is_doc_file, read_doc_stamp_source
from core.hasher import (
    RESULT_ALREADY_EXISTS,
    RESULT_NEW,
    RESULT_NEW_VARIANT,
    RESULT_NEW_VERSION,
    process_file_entry,
)
from core.parsers.stamp_parser import parse_stamp
from core.statuses import UiStatus

CONVERTED_DIR = os.path.join("data", "converted")

RESULT_TO_UI = {
    RESULT_NEW: UiStatus.FOUND,
    RESULT_NEW_VERSION: UiStatus.FOUND,
    RESULT_ALREADY_EXISTS: UiStatus.EXISTS,
    RESULT_NEW_VARIANT: UiStatus.VARIANTS,
}

StampReader = Callable[[str], dict[str, Any]]


def read_stamp(path: str) -> dict[str, Any]:
    """Штамп файла; для .doc — через конвертацию в .docx."""
    stamp_path = read_doc_stamp_source(path, CONVERTED_DIR)
    stamp = parse_stamp(stamp_path)
    if is_doc_file(path) and stamp_path == path:
        stamp["stamp_status"] = "UNSUPPORTED"
    return stamp


class FileRegistrar:
    """Вызываемый объект для `SearchManager.start_search(on_file=...)`.

    Соединение с SQLite открывается на каждый файл в рабочем потоке:
    так оно не пересекает границы потоков.
    """

    def __init__(self, db_path: str | None = None, stamp_reader: StampReader | None = None) -> None:
        self.db_path = db_path
        self.stamp_reader = stamp_reader or read_stamp
        self._lock = threading.Lock()
        self.items: list[dict[str, Any]] = []

    def __call__(self, path: str) -> None:
        stamp = self.stamp_reader(path)
        connection = database.init_db(self.db_path)
        try:
            result = process_file_entry(path, connection, stamp=stamp)
        finally:
            connection.close()
        item = {
            "path": result["path"],
            "file_id": result["file_id"],
            "hash": result["hash"],
            "doc_code": result["doc_code"],
            "revision": result["revision"],
            "revision_date": result["revision_date"],
            "revision_date_source": result.get("revision_date_source", ""),
            "result": result["result"],
            "ui_status": RESULT_TO_UI[result["result"]].value,
        }
        with self._lock:
            self.items.append(item)

    def get_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.items)

    def clear(self) -> None:
        with self._lock:
            self.items = []
