"""API-слой для GUI (Этап 3.6): вся бизнес-логика, которую вызывает интерфейс.

`Controller` связывает `SearchManager`, `FileRegistrar` и `TaskManager`.
Модульные функции `start_search`, `stop_search`, `get_status`, `get_files`,
`process_selected`, `prepare_selected` работают через общий экземпляр.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterable
from typing import Any

from core import database, excel_refresh, exports, header_dictionary, kits, query_builder, reference_exchange, reference_store
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
        name_words: Iterable[str] | None = None,
        folder_filters: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if isinstance(directories, str):
            directories = [directories]
        directories = [d for d in directories if d]
        if not directories:
            return {"status": "error", "message": "Не указаны папки для поиска"}
        with self._lock:
            self.registrar.clear()
            started = self.search.start_search(
                directories, mask or "*", on_file=self.registrar, name_words=name_words,
                folder_filters=folder_filters,
            )
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
            try:
                meta = json.loads(item.get("meta_json") or "{}")
            except ValueError:
                meta = {}
            item["revision_date_source"] = meta.get("revision_date_source", "")
            item.update(kits.kit_info(item))
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

    def check_kits(self, file_ids: list[int]) -> dict[str, Any]:
        """Перед «Сохранить»: документы, не принадлежащие своему комплекту."""
        connection = database.init_db(self.db_path)
        try:
            rows = [
                row
                for row in (database.get_file_by_id(connection, int(i)) for i in file_ids or [])
                if row
            ]
        finally:
            connection.close()
        return {"status": "ok", "conflicts": kits.check_kits(rows)}

    def process_selected(
        self, file_ids: list[int], force_ids: Iterable[int] | None = None
    ) -> dict[str, Any]:
        """«Сохранить»: фоновый разбор выбранных файлов.

        `force_ids` — документы, которые пользователь принял в комплект вручную:
        они получают `meta_json.kit_forced` и помечаются в списке.
        """
        force = {int(i) for i in force_ids or []}
        if force:
            connection = database.init_db(self.db_path)
            try:
                for file_id in force:
                    database.update_file_meta_by_id(connection, file_id, {"kit_forced": True})
            finally:
                connection.close()
        return {"status": "started", "queued": self.tasks.save_files(file_ids)}

    def prepare_selected(self, file_ids: list[int] | None = None) -> dict[str, Any]:
        """«Подготовить»: маппинг актуальных SAVED-файлов."""
        return {"status": "started", "queued": self.tasks.prepare_files(file_ids)}

    def build_queries(self, file_ids: list[int], opener=None, mode: str = query_builder.MODE_BY_TYPE,
                      refresher=None) -> dict[str, Any]:
        """«Сформировать запросы»: копия шаблона по типу (`by_type`) или общая книга ВОР+СО (`vor_so`)."""
        if not file_ids:
            return {"status": "error", "message": "Не выбрано ни одного файла"}
        try:
            result = query_builder.build_queries(file_ids, self.db_path, mode=mode)
        except query_builder.QueryBuildError as exc:
            return {"status": "error", "message": str(exc)}
        if not result["books"]:
            reasons = "; ".join(sorted({s["reason"] for s in result["skipped"]})) or "нет подходящих файлов"
            return {"status": "error", "message": "Запросы не сформированы: " + reasons, **result}
        opener = opener or _open_in_system
        to_open = result["books"]
        refresh = None
        if mode == query_builder.MODE_VOR_SO:
            # ВОР и СО обновляются и сохраняются первыми, затем ВОР+СО (она читает их файлы); открывается только ВОР+СО.
            refresher = refresher or excel_refresh.refresh_books
            refresh = refresher([b["path"] for b in result["books"]])
            if refresh["status"] == "ok":
                to_open = result["books"][-1:]
        for book in to_open:
            try:
                opener(book["path"])
            except OSError:
                pass  # книга создана; не открылась — путь есть в ответе
        out = {"status": "ok", **result}
        if refresh is not None:
            out["refresh"] = refresh
        return out

    def reconcile_report(self, opener=None, runner=None, folder: str | None = None) -> dict[str, Any]:
        """«Отчёт ВОР+СО»: сверка итогов последнего комплекта книг и открытие файла."""
        runner = runner or excel_refresh.make_reconcile_report
        result = runner(folder or query_builder.QUERIES_DIR)
        if result.get("status") == "ok":
            try:
                (opener or _open_in_system)(result["path"])
            except OSError:
                pass  # отчёт создан; путь есть в ответе
        return result

    def check_headers(self, file_ids: list[int]) -> dict[str, Any]:
        """Перед «Сформировать запросы»: заголовки CSV без канонической роли."""
        result = query_builder.analyze_headers(file_ids, self.db_path)
        return {"status": "ok", **result}

    def apply_header_decisions(self, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Решения по заголовкам: assign (role), new (role), ignore (навсегда), skip (ничего)."""
        done, errors = 0, []
        connection = database.init_db(self.db_path)
        try:
            for item in decisions or []:
                header, action = item.get("header") or "", item.get("action")
                role = (item.get("role") or "").strip()
                try:
                    if action == "assign":
                        header_dictionary.set_alias(connection, role, header)
                    elif action == "new":
                        role = header_dictionary.add_canonical(connection, role or header)
                        header_dictionary.set_alias(connection, role, header)
                    elif action == "ignore":
                        header_dictionary.ignore_header(connection, header)
                    elif action != "skip":
                        continue
                    done += action != "skip"
                except header_dictionary.DictionaryError as exc:
                    errors.append(f"{header}: {exc}")
        finally:
            connection.close()
        return {"status": "error" if errors else "ok", "applied": done, "errors": errors,
                "message": "; ".join(errors)}

    def get_dictionary(self) -> dict[str, Any]:
        connection = database.init_db(self.db_path)
        try:
            return {"status": "ok", **header_dictionary.list_dictionary(connection)}
        finally:
            connection.close()

    def edit_dictionary(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Правка справочника: add_alias, remove_alias, add_canonical, rename_canonical,
        delete_canonical, unignore."""
        args = args or {}
        hd = header_dictionary
        operations = {
            "add_alias": lambda c: hd.set_alias(c, args.get("canonical", ""), args.get("text", "")),
            "remove_alias": lambda c: hd.remove_alias(c, args.get("key", "")),
            "add_canonical": lambda c: hd.add_canonical(c, args.get("name", "")),
            "rename_canonical": lambda c: hd.rename_canonical(c, args.get("old", ""), args.get("new", "")),
            "delete_canonical": lambda c: hd.delete_canonical(c, args.get("name", "")),
            "unignore": lambda c: hd.unignore_header(c, args.get("key", "")),
            "ignore": lambda c: hd.ignore_header(c, args.get("text", "")),
            "rename_alias": lambda c: hd.rename_alias(
                c, args.get("key", ""), args.get("canonical", ""), args.get("text", "")),
            "rename_ignored": lambda c: hd.rename_ignored(c, args.get("key", ""), args.get("text", "")),
        }
        if op not in operations:
            return {"status": "error", "message": f"Неизвестная операция: {op}"}
        connection = database.init_db(self.db_path)
        try:
            operations[op](connection)
        except header_dictionary.DictionaryError as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            connection.close()
        return self.get_dictionary()

    def get_reference(self) -> dict[str, Any]:
        connection = database.init_db(self.db_path)
        try:
            return {"status": "ok", **reference_store.list_reference(connection)}
        finally:
            connection.close()

    def edit_reference(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Правка справочника помещений: add_/update_/delete_ + building, floor, room."""
        a = args or {}
        rs = reference_store
        operations = {
            "add_building": lambda c: rs.add_building(c, a.get("code"), a.get("name"), a.get("full")),
            "update_building": lambda c: rs.update_building(c, a.get("id"), a.get("code"), a.get("name"), a.get("full")),
            "delete_building": lambda c: rs.delete_building(c, a.get("id")),
            "add_floor": lambda c: rs.add_floor(c, a.get("building_id"), a.get("code"), a.get("name"), a.get("ground")),
            "update_floor": lambda c: rs.update_floor(c, a.get("id"), a.get("code"), a.get("name"), a.get("ground")),
            "delete_floor": lambda c: rs.delete_floor(c, a.get("id")),
            "add_room": lambda c: rs.add_room(c, a.get("floor_id"), a.get("code"), a.get("name"), a.get("ground")),
            "update_room": lambda c: rs.update_room(c, a.get("id"), a.get("code"), a.get("name"), a.get("ground")),
            "delete_room": lambda c: rs.delete_room(c, a.get("id")),
        }
        if op not in operations:
            return {"status": "error", "message": f"Неизвестная операция: {op}"}
        connection = database.init_db(self.db_path)
        try:
            operations[op](connection)
        except reference_store.ReferenceError_ as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            connection.close()
        return self.get_reference()

    def export_reference(self, path: str) -> dict[str, Any]:
        """Выгрузка справочника в xlsx (листы Здания, Этажи, Помещения)."""
        if not path:
            return {"status": "cancelled"}
        if not str(path).lower().endswith(".xlsx"):
            path = f"{path}.xlsx"
        connection = database.init_db(self.db_path)
        try:
            counts = reference_exchange.export_xlsx(connection, path)
        except OSError as exc:
            return {"status": "error", "message": f"Не удалось записать файл: {exc}"}
        finally:
            connection.close()
        return {"status": "ok", "path": path, **counts}

    def import_reference(self, path: str) -> dict[str, Any]:
        """Загрузка справочника из xlsx: добавляет и обновляет, ничего не удаляет."""
        if not path:
            return {"status": "cancelled"}
        connection = database.init_db(self.db_path)
        try:
            result = reference_exchange.import_xlsx(connection, path)
        except reference_store.ReferenceError_ as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - битый файл, нет листа и т.п.
            return {"status": "error", "message": f"Не удалось прочитать файл: {exc}"}
        finally:
            connection.close()
        return {"status": "ok", "added": result["added"], "updated": result["updated"],
                "reference": self.get_reference()}

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

    def open_csv(self, file_id: int, opener=None) -> dict[str, Any]:
        """Временное решение: двойной щелчок по сохранённому файлу открывает его CSV."""
        opener = opener or _open_in_system
        connection = database.init_db(self.db_path)
        try:
            row = database.get_file_by_id(connection, int(file_id))
        finally:
            connection.close()
        joined = (row or {}).get("csv_path") or ""
        paths = [p.strip() for p in str(joined).split(";") if p.strip()]
        if not paths:
            return {"status": "error", "message": "У файла нет сохранённого CSV"}
        existing = [p for p in paths if os.path.isfile(p)]
        if not existing:
            return {"status": "error", "message": "CSV не найден на диске: " + paths[0]}
        for path in existing:
            opener(os.path.abspath(path))
        return {"status": "ok", "opened": existing}

    def open_document(self, path: str, opener=None) -> dict[str, Any]:
        """Открывает исходный документ (.doc/.docx) в Word (программа по умолчанию)."""
        opener = opener or _open_in_system
        path = str(path or "")
        if not path.lower().endswith((".doc", ".docx")):
            return {"status": "error", "message": "Это не документ Word: " + path}
        if not os.path.isfile(path):
            return {"status": "error", "message": "Файл не найден: " + path}
        opener(os.path.abspath(path))
        return {"status": "ok", "opened": path}

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


def _open_in_system(path: str) -> None:
    """Открывает файл программой по умолчанию (Windows, macOS, Linux)."""
    if hasattr(os, "startfile"):
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        import subprocess
        import sys

        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


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


def list_subfolders(root: str) -> dict[str, Any]:
    """Папки первого уровня корневой папки: из них пользователь выбирает комплекты."""
    if not root or not os.path.isdir(root):
        return {"status": "error", "message": "Корневая папка не найдена", "folders": []}
    try:
        names = sorted(
            (n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith(".")),
            key=str.casefold,
        )
    except OSError as exc:
        return {"status": "error", "message": str(exc), "folders": []}
    return {"status": "ok", "folders": names}


def get_controller() -> Controller:
    global _default
    with _default_lock:
        if _default is None:
            _default = Controller(
                search=SearchManager.get_instance(), tasks=TaskManager.get_instance()
            )
        return _default


def start_search(
    directories, mask: str = "*", background_mode: bool = True, name_words=None,
    folder_filters=None,
) -> dict[str, Any]:
    return get_controller().start_search(
        directories, mask, background_mode, name_words, folder_filters
    )


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


def open_csv(file_id) -> dict[str, Any]:
    return get_controller().open_csv(file_id)


def open_document(path) -> dict[str, Any]:
    return get_controller().open_document(path)


def process_selected(file_ids: list[int], force_ids=None) -> dict[str, Any]:
    return get_controller().process_selected(file_ids, force_ids)


def check_kits(file_ids: list[int]) -> dict[str, Any]:
    return get_controller().check_kits(file_ids)


def prepare_selected(file_ids: list[int] | None = None) -> dict[str, Any]:
    return get_controller().prepare_selected(file_ids)


def build_queries(file_ids: list[int], mode: str = query_builder.MODE_BY_TYPE) -> dict[str, Any]:
    return get_controller().build_queries(file_ids, mode=mode)


def reconcile_report() -> dict[str, Any]:
    return get_controller().reconcile_report()


def check_headers(file_ids: list[int]) -> dict[str, Any]:
    return get_controller().check_headers(file_ids)


def apply_header_decisions(decisions) -> dict[str, Any]:
    return get_controller().apply_header_decisions(decisions)


def get_dictionary() -> dict[str, Any]:
    return get_controller().get_dictionary()


def edit_dictionary(op: str, args=None) -> dict[str, Any]:
    return get_controller().edit_dictionary(op, args)


def get_reference() -> dict[str, Any]:
    return get_controller().get_reference()


def edit_reference(op: str, args=None) -> dict[str, Any]:
    return get_controller().edit_reference(op, args)


def export_reference(path) -> dict[str, Any]:
    return get_controller().export_reference(path)


def import_reference(path) -> dict[str, Any]:
    return get_controller().import_reference(path)
