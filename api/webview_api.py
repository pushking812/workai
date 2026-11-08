"""Мост JS -> Python для PyWebView (Этап 4.1).

Класс `Api` тонкий: методы один в один вызывают функции `api.controller`,
где находится вся бизнес-логика. Исключение — системные диалоги, они
требуют окна PyWebView.
"""

from __future__ import annotations

from typing import Any

from api import controller
from core import config

FILE_TYPES = ("Word Documents (*.docx;*.doc)",)


def _first_window():
    import webview

    return webview.windows[0] if webview.windows else None


def _dialog_kind(webview, name: str):
    """`FileDialog.<name>` в новых версиях pywebview, `<name>_DIALOG` в старых."""
    file_dialog = getattr(webview, "FileDialog", None)
    if file_dialog is not None:
        return getattr(file_dialog, name)
    return getattr(webview, f"{name}_DIALOG")


class Api:
    def ping(self) -> str:
        return "pong"

    def start_search(self, directories, mask: str = "*", background_mode: bool = True) -> dict[str, Any]:
        return controller.start_search(directories, mask, background_mode)

    def get_settings(self) -> dict[str, Any]:
        return config.load_config()

    def save_settings(self, settings) -> dict[str, Any]:
        return config.save_config(settings or {})

    def stop_search(self) -> dict[str, Any]:
        return controller.stop_search()

    def get_status(self) -> dict[str, Any]:
        return controller.get_status()

    def get_files(self) -> dict[str, Any]:
        return controller.get_files()

    def process_manual_add(self, paths) -> dict[str, Any]:
        return controller.add_files(paths)

    def process_selected(self, file_ids) -> dict[str, Any]:
        return controller.process_selected(file_ids)

    def prepare_selected(self, file_ids=None) -> dict[str, Any]:
        return controller.prepare_selected(file_ids)

    def stop_tasks(self) -> dict[str, Any]:
        return controller.stop_tasks()

    def hide_files(self, file_ids) -> dict[str, Any]:
        return controller.hide_files(file_ids)

    def restore_files(self, file_ids) -> dict[str, Any]:
        return controller.restore_files(file_ids)

    def clear_database(self) -> dict[str, Any]:
        return controller.clear_database()

    def exit_app(self) -> None:
        """Кнопка «Выход»: останавливает фоновые задачи и закрывает окно."""
        controller.stop_search()
        controller.stop_tasks()
        window = _first_window()
        if window is not None:
            window.destroy()

    def add_files_dialog(self) -> list[str]:
        """Диалог выбора файлов; возвращает пути (пустой список при отмене)."""
        import webview

        window = _first_window()
        if window is None:
            return []
        paths = window.create_file_dialog(
            _dialog_kind(webview, "OPEN"), allow_multiple=True, file_types=FILE_TYPES
        )
        return list(paths or [])

    def choose_folder(self) -> str:
        """Диалог выбора папки для поиска; пустая строка при отмене."""
        import webview

        window = _first_window()
        if window is None:
            return ""
        paths = window.create_file_dialog(_dialog_kind(webview, "FOLDER"))
        return paths[0] if paths else ""
