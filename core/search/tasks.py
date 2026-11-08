"""Очередь фоновых задач (Этап 3.5).

`TaskManager` держит один рабочий поток и очередь задач двух видов:

* «Сохранить» — файл `SAVED` -> `PROCESSING` -> `SAVED` (CSV записан) или `ERROR`;
* «Подготовить» — актуальный (`is_current = 1`) файл `SAVED` -> `PROCESSING` ->
  `READY` (все заголовки сопоставлены) или `NEEDS_MAPPING`.

Ошибка одного файла пишется в `error_message`, поток идёт к следующему.
Соединение SQLite открывается внутри рабочего потока.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from typing import Any

from core import database, exports
from core.statuses import FileStatus
from core.transformer.fuzzy_matcher import find_best_match

KIND_SAVE = "save"
KIND_PREPARE = "prepare"

# saver(path, file_hash, connection, exports_dir) -> пути CSV через ';' ('' — таблиц нет)
Saver = Callable[[str, str, Any, str], str]


def default_saver(path: str, file_hash: str, connection: Any, exports_dir: str) -> str:
    """Парсер -> CSV: тот же пайплайн, что и у `scripts.process_folder`."""
    from core.doc_converter import read_doc_stamp_source
    from scripts.process_folder import CONVERTED_DIR, export_tables

    source = read_doc_stamp_source(path, CONVERTED_DIR)
    return export_tables(source, file_hash, exports_dir, connection)


class TaskManager:
    _instance: "TaskManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: str | None = None, saver: Saver | None = None) -> None:
        self.db_path = db_path
        self.saver = saver or default_saver
        self._queue: "queue.Queue[tuple[str, int]]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.processed = 0
        self.pending = 0
        self.errors: list[str] = []

    @classmethod
    def get_instance(cls) -> "TaskManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # --- постановка задач -------------------------------------------------

    def save_files(self, file_ids: list[int]) -> int:
        """Ставит файлы в очередь «Сохранить». Возвращает число принятых."""
        return self._enqueue(KIND_SAVE, file_ids)

    def prepare_files(self, file_ids: list[int] | None = None) -> int:
        """Ставит в очередь «Подготовить»; без списка — все актуальные `SAVED`."""
        if file_ids is None:
            connection = database.init_db(self.db_path)
            try:
                rows = database.list_files(
                    connection, status=FileStatus.SAVED.value, only_current=True
                )
            finally:
                connection.close()
            file_ids = [row["id"] for row in rows]
        return self._enqueue(KIND_PREPARE, file_ids)

    def _enqueue(self, kind: str, file_ids: list[int]) -> int:
        ids = list(dict.fromkeys(int(i) for i in file_ids))
        with self._lock:
            for file_id in ids:
                self._queue.put((kind, file_id))
            self.pending += len(ids)
            if ids and (self._thread is None or not self._thread.is_alive()):
                self._stop.clear()
                self._thread = threading.Thread(target=self._worker, daemon=True)
                self._thread.start()
        return len(ids)

    # --- управление -------------------------------------------------------

    def stop(self) -> None:
        """Просит поток остановиться после текущего файла; очередь сбрасывается."""
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.is_running(),
                "processed": self.processed,
                "pending": self.pending,
                "errors": list(self.errors),
            }

    # --- рабочий поток ----------------------------------------------------

    def _worker(self) -> None:
        connection = database.init_db(self.db_path)
        exports_dir = exports.exports_dir_for(
            self.db_path or database.DB_PATH, os.path.join("data", "exports")
        )
        os.makedirs(exports_dir, exist_ok=True)
        try:
            while True:
                if self._stop.is_set():
                    self._drain()
                    return
                with self._lock:
                    try:
                        kind, file_id = self._queue.get_nowait()
                    except queue.Empty:
                        self._thread = None
                        return
                try:
                    if kind == KIND_SAVE:
                        self._save(connection, file_id, exports_dir)
                    else:
                        self._prepare(connection, file_id)
                except Exception as error:  # noqa: BLE001
                    self._fail(connection, file_id, error)
                finally:
                    with self._lock:
                        self.processed += 1
                        self.pending = max(0, self.pending - 1)
        finally:
            connection.close()

    def _drain(self) -> None:
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self.pending = 0
            self._thread = None

    def _fail(self, connection: Any, file_id: int, error: Exception) -> None:
        message = "%s: %s" % (type(error).__name__, error)
        with self._lock:
            self.errors.append("%d: %s" % (file_id, message))
        try:
            database.update_file_status(
                connection, file_id, FileStatus.ERROR.value, error_message=message
            )
        except Exception:  # noqa: BLE001
            pass

    def _save(self, connection: Any, file_id: int, exports_dir: str) -> None:
        document = database.get_file_by_id(connection, file_id)
        if document is None:
            raise LookupError("файл не найден в базе")
        database.update_file_status(connection, file_id, FileStatus.PROCESSING.value)
        csv_path = self.saver(document["path"], document["hash"], connection, exports_dir)
        if not csv_path:
            raise ValueError("таблицы не извлечены")
        database.update_file_status(connection, file_id, FileStatus.SAVED.value, csv_path)

    def _prepare(self, connection: Any, file_id: int) -> None:
        document = database.get_file_by_id(connection, file_id)
        if document is None:
            raise LookupError("файл не найден в базе")
        if document.get("is_current") != 1 or document["status"] != FileStatus.SAVED.value:
            return  # только актуальные SAVED; остальные не трогаем
        database.update_file_status(connection, file_id, FileStatus.PROCESSING.value)
        status, message = self._map_schema(connection, document.get("schema_hash"))
        database.update_file_status(connection, file_id, status.value, error_message=message)

    @staticmethod
    def _map_schema(connection: Any, schema_hash: str | None) -> tuple[FileStatus, str | None]:
        """Сопоставляет заголовки схемы с каноническими именами (Этап 2)."""
        schema = database.get_schema(connection, schema_hash) if schema_hash else None
        if schema is None:
            return FileStatus.NEEDS_MAPPING, "схема таблицы не определена"
        if schema["mapping"]:
            return FileStatus.READY, None
        mapping: dict[str, str] = {}
        unresolved: list[str] = []
        for header in schema["normalized_headers"]:
            if not header:
                continue
            match = find_best_match(connection, header)
            if match["requires_manual_review"] or not match["suggested_canonical"]:
                unresolved.append(header)
            else:
                mapping[header] = match["suggested_canonical"]
        if unresolved:
            return FileStatus.NEEDS_MAPPING, "не сопоставлены: " + "; ".join(unresolved)
        database.set_schema_mapping(connection, schema["schema_hash"], mapping)
        return FileStatus.READY, None
