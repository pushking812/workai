"""Фоновый поиск файлов с остановкой (Этап 3.2)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from core.search.scanner import DEFAULT_EXTENSIONS, scan_files

FileCallback = Callable[[str], None]


class SearchManager:
    """Запускает `scan_files` в фоновом потоке; один поиск за раз.

    `on_file` вызывается в рабочем потоке для каждого найденного файла
    (в Этапе 3.4 сюда подключается запись в БД). Ошибка в `on_file`
    не прерывает поиск, а попадает в `errors`.
    """

    _instance: "SearchManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.processed_files = 0
        self.total_found = 0
        self.found_paths: list[str] = []
        self.errors: list[str] = []
        self.stopped = False

    @classmethod
    def get_instance(cls) -> "SearchManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def is_running(self) -> bool:
        thread = self.thread
        return thread is not None and thread.is_alive()

    def start_search(
        self,
        directories: Iterable[str],
        mask: str = "*",
        on_file: FileCallback | None = None,
        extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
        name_words: Iterable[str] | None = None,
        folder_filters: Iterable[str] | None = None,
    ) -> bool:
        """Запускает поиск. False, если поиск уже идёт."""
        with self._lock:
            if self.is_running():
                return False
            self.stop_event.clear()
            self.processed_files = 0
            self.total_found = 0
            self.found_paths = []
            self.errors = []
            self.stopped = False
            self.thread = threading.Thread(
                target=self._search_worker,
                args=(
                    list(directories), mask, on_file, extensions,
                    list(name_words or ()), list(folder_filters or ()),
                ),
                daemon=True,
            )
            self.thread.start()
            return True

    def stop_search(self) -> None:
        """Просит поток остановиться; он завершится на следующей итерации."""
        self.stop_event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Ждёт конца потока. True, если поток завершён."""
        thread = self.thread
        if thread is not None:
            thread.join(timeout)
        return not self.is_running()

    def get_status(self) -> dict:
        return {
            "running": self.is_running(),
            "stopping": self.is_running() and self.stop_event.is_set(),
            "stopped": self.stopped,
            "processed_files": self.processed_files,
            "total_found": self.total_found,
            "errors": list(self.errors),
        }

    def _search_worker(
        self,
        directories: list[str],
        mask: str,
        on_file: FileCallback | None,
        extensions: tuple[str, ...],
        name_words: list[str] | None = None,
        folder_filters: list[str] | None = None,
    ) -> None:
        for path in scan_files(
            directories, mask, extensions, self.stop_event.is_set, name_words, folder_filters
        ):
            if self.stop_event.is_set():
                break
            self.total_found += 1
            self.found_paths.append(path)
            if on_file is not None:
                try:
                    on_file(path)
                except Exception as exc:  # noqa: BLE001 — поиск должен идти дальше
                    self.errors.append(f"{path}: {exc}")
            self.processed_files += 1
        self.stopped = self.stop_event.is_set()
