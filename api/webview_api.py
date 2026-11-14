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
        settings = config.load_config()
        words = config.search_words(settings)
        return controller.start_search(
            directories, mask, background_mode, words, settings.get("folder_filters")
        )

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

    def check_kits(self, file_ids) -> dict[str, Any]:
        return controller.check_kits(file_ids)

    def process_selected(self, file_ids, force_ids=None) -> dict[str, Any]:
        if force_ids:
            return controller.process_selected(file_ids, force_ids)
        return controller.process_selected(file_ids)

    def prepare_selected(self, file_ids=None) -> dict[str, Any]:
        return controller.prepare_selected(file_ids)

    def build_queries(self, file_ids, mode="by_type") -> dict[str, Any]:
        return controller.build_queries(file_ids, mode=mode)

    def reconcile_report(self) -> dict[str, Any]:
        return controller.reconcile_report()

    def check_headers(self, file_ids) -> dict[str, Any]:
        return controller.check_headers(file_ids)

    def apply_header_decisions(self, decisions) -> dict[str, Any]:
        return controller.apply_header_decisions(decisions)

    def get_dictionary(self) -> dict[str, Any]:
        return controller.get_dictionary()

    def edit_dictionary(self, op, args=None) -> dict[str, Any]:
        return controller.edit_dictionary(op, args)

    def stop_tasks(self) -> dict[str, Any]:
        return controller.stop_tasks()

    def hide_files(self, file_ids) -> dict[str, Any]:
        return controller.hide_files(file_ids)

    def restore_files(self, file_ids) -> dict[str, Any]:
        return controller.restore_files(file_ids)

    def open_csv(self, file_id) -> dict[str, Any]:
        return controller.open_csv(file_id)

    def open_document(self, path) -> dict[str, Any]:
        return controller.open_document(path)

    def clear_database(self) -> dict[str, Any]:
        return controller.clear_database()

    def list_subfolders(self, root) -> dict[str, Any]:
        return controller.list_subfolders(root)

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
        """Диалог выбора корневой папки; пустая строка при отмене."""
        import webview

        window = _first_window()
        if window is None:
            return ""
        paths = window.create_file_dialog(_dialog_kind(webview, "FOLDER"))
        return paths[0] if paths else ""
