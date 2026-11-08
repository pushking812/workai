"""API-слой для GUI (Этап 3.6): вся бизнес-логика, которую вызывает интерфейс.

`Controller` связывает `SearchManager`, `FileRegistrar` и `TaskManager`.
Модульные функции `start_search`, `stop_search`, `get_status`, `get_files`,
`process_selected`, `prepare_selected` работают через общий экземпляр.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterable
from typing import Any

from core import database, exports
from core.statuses import FileStatus
from core.search.manager import SearchManager
from core.search.registrar import FileRegistrar
from core.search.tasks import TaskManager


class Controller:
    def __init__(
        self,
        db_path: str | None = None,
        search: SearchManager | None = None,
        tasks: TaskManager | None = None,
        registrar: FileRegistrar | None = None,
    ) -> None:
        self.db_path = db_path
        self.search = search or SearchManager()
        self.tasks = tasks or TaskManager(db_path)
        self.registrar = registrar or FileRegistrar(db_path)
        self._started_at: float | None = None
        self._lock = threading.Lock()

    def start_search(
        self,
        directories: Iterable[str] | str,
        mask: str = "*",
        background_mode: bool = True,
    ) -> dict[str, Any]:
        if isinstance(directories, str):
            directories = [directories]
        directories = [d for d in directories if d]
        if not directories:
            return {"status": "error", "message": "Не указаны папки для поиска"}
        with self._lock:
            self.registrar.clear()
            started = self.search.start_search(directories, mask or "*", on_file=self.registrar)
            if started:
                self._started_at = time.monotonic()
        if not started:
            return {"status": "already_running"}
        if not background_mode:
            self.search.wait()
        return {"status": "started"}

    def stop_search(self) -> dict[str, Any]:
        self.search.stop_search()
        return {"status": "stopping"}

    def get_status(self) -> dict[str, Any]:
        status = self.search.get_status()
        elapsed = (time.monotonic() - self._started_at) if self._started_at else 0.0
        speed = status["processed_files"] / elapsed if elapsed > 0 else 0.0
        return {
            "search": {**status, "files_per_sec": round(speed, 2)},
            "tasks": self.tasks.get_status(),
        }

    def get_files(self) -> dict[str, Any]:
        """Файлы из БД и найденные поиском (с UI-статусами FOUND/EXISTS/VARIANTS)."""
        connection = database.init_db(self.db_path)
        try:
            rows = database.list_files(connection)
        finally:
            connection.close()
        found = self.registrar.get_items()
        for item in rows:
            item.update(_file_stat(item.get("path")))
        for item in found:
            item.update(_file_stat(item.get("path")))
            item["filename"] = os.path.basename(item.get("path") or "")
        return {"files": rows, "found": found}

    def add_files(self, paths: Iterable[str]) -> dict[str, Any]:
        """Ручное добавление: те же правила версий, что и у поиска."""
        added = 0
        errors: list[str] = []
        for path in paths or []:
            try:
                self.registrar(path)
                added += 1
            except Exception as exc:  # noqa: BLE001 — остальные файлы обрабатываем дальше
                errors.append(f"{path}: {exc}")
        return {"status": "ok", "added": added, "errors": errors}

    def process_selected(self, file_ids: list[int]) -> dict[str, Any]:
        """«Сохранить»: фоновый разбор выбранных файлов."""
        return {"status": "started", "queued": self.tasks.save_files(file_ids)}

    def prepare_selected(self, file_ids: list[int] | None = None) -> dict[str, Any]:
        """«Подготовить»: маппинг актуальных SAVED-файлов."""
        return {"status": "started", "queued": self.tasks.prepare_files(file_ids)}

    def stop_tasks(self) -> dict[str, Any]:
        self.tasks.stop()
        return {"status": "stopping"}

    def hide_files(self, file_ids: Iterable[int]) -> dict[str, Any]:
        """«Скрыть выделенные»: статус HIDDEN, в обычном списке файлы не показываются."""
        return self._set_status(file_ids, FileStatus.HIDDEN.value, only_not=FileStatus.HIDDEN.value)

    def restore_files(self, file_ids: Iterable[int]) -> dict[str, Any]:
        """Возврат скрытых файлов в список (статус SAVED)."""
        return self._set_status(file_ids, FileStatus.SAVED.value, only=FileStatus.HIDDEN.value)

    def _set_status(
        self,
        file_ids: Iterable[int],
        status: str,
        only: str | None = None,
        only_not: str | None = None,
    ) -> dict[str, Any]:
        changed = 0
        connection = database.init_db(self.db_path)
        try:
            for file_id in dict.fromkeys(int(i) for i in file_ids or []):
                row = database.get_file_by_id(connection, file_id)
                if row is None:
                    continue
                if only is not None and row["status"] != only:
                    continue
                if only_not is not None and row["status"] == only_not:
                    continue
                database.update_file_status(connection, file_id, status)
                changed += 1
        finally:
            connection.close()
        return {"status": "ok", "changed": changed}

    def clear_database(self) -> dict[str, Any]:
        """Удаляет все записи о файлах и все CSV этой БД.

        Справочник синонимов и схемы таблиц не трогаем. Во время поиска или
        обработки очистка отклоняется.
        """
        if self.search.get_status().get("running") or self.tasks.is_running():
            return {"status": "busy", "message": "Дождитесь окончания поиска и обработки"}
        db_path = self.db_path or database.DB_PATH
        csv_files: set[str] = set()
        connection = database.init_db(self.db_path)
        try:
            for (joined,) in connection.execute(
                "SELECT csv_path FROM files WHERE csv_path IS NOT NULL AND csv_path <> ''"
            ).fetchall():
                csv_files.update(p.strip() for p in str(joined).split(";") if p.strip())
            removed = connection.execute("DELETE FROM files").rowcount
            connection.commit()
        finally:
            connection.close()
        folder = exports.exports_dir_for(db_path)
        if os.path.isdir(folder):
            for current, _dirs, names in os.walk(folder):
                csv_files.update(os.path.join(current, n) for n in names if n.lower().endswith(".csv"))
        deleted = 0
        for path in csv_files:
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass
        self.registrar.clear()
        return {"status": "ok", "records": removed, "csv_deleted": deleted}


def _file_stat(path: str | None) -> dict[str, Any]:
    """Размер и время изменения файла на диске (None, если файла нет)."""
    try:
        info = os.stat(path) if path else None
    except OSError:
        info = None
    if info is None:
        return {"size": None, "file_mtime": None}
    return {"size": info.st_size, "file_mtime": info.st_mtime}


_default: Controller | None = None
_default_lock = threading.Lock()


def get_controller() -> Controller:
    global _default
    with _default_lock:
        if _default is None:
            _default = Controller(
                search=SearchManager.get_instance(), tasks=TaskManager.get_instance()
            )
        return _default


def start_search(directories, mask: str = "*", background_mode: bool = True) -> dict[str, Any]:
    return get_controller().start_search(directories, mask, background_mode)


def stop_search() -> dict[str, Any]:
    return get_controller().stop_search()


def get_status() -> dict[str, Any]:
    return get_controller().get_status()


def get_files() -> dict[str, Any]:
    return get_controller().get_files()


def add_files(paths) -> dict[str, Any]:
    return get_controller().add_files(paths)


def stop_tasks() -> dict[str, Any]:
    return get_controller().stop_tasks()


def hide_files(file_ids) -> dict[str, Any]:
    return get_controller().hide_files(file_ids)


def restore_files(file_ids) -> dict[str, Any]:
    return get_controller().restore_files(file_ids)


def clear_database() -> dict[str, Any]:
    return get_controller().clear_database()


def process_selected(file_ids: list[int]) -> dict[str, Any]:
    return get_controller().process_selected(file_ids)


def prepare_selected(file_ids: list[int] | None = None) -> dict[str, Any]:
    return get_controller().prepare_selected(file_ids)
