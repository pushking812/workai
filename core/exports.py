"""Соответствие «БД -> папка с CSV»: путь экспорта, сверка, удаление БД.

У каждой БД своя подпапка внутри `data/exports/`: `data/exports/<имя_бд>/`.
Источник истины — БД: актуальным считается CSV, путь которого записан в
`files.csv_path`. Всё остальное в подпапке — «сироты».
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from typing import Any

EXPORTS_ROOT = os.path.join("data", "exports")
ARCHIVE_ROOT = os.path.join("data", "archive")
ORPHANS_DIR = "_orphans"
REPORT_PREFIX = "_report_"
DB_SIDECARS = ("-wal", "-shm", "-journal")


def db_stem(db_path: str) -> str:
    return os.path.splitext(os.path.basename(db_path))[0]


def exports_dir_for(db_path: str, root: str = EXPORTS_ROOT) -> str:
    """Подпапка экспорта, принадлежащая только этой БД."""
    return os.path.join(root, db_stem(db_path))


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([_norm(path), _norm(folder)]) == _norm(folder)
    except ValueError:  # разные диски
        return False


def referenced_csv(db_path: str) -> list[tuple[int, str]]:
    """Все пары (id записи, путь CSV) из БД. БД не изменяется."""
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT id, csv_path FROM files WHERE csv_path IS NOT NULL AND csv_path <> ''"
        ).fetchall()
    finally:
        connection.close()
    result: list[tuple[int, str]] = []
    for file_id, joined in rows:
        for path in str(joined).split(";"):
            if path.strip():
                result.append((int(file_id), path.strip()))
    return result


def _walk_files(folder: str, skip_dirs: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        found.extend(os.path.join(current, name) for name in files)
    return sorted(found)


def check_exports(db_path: str, root: str = EXPORTS_ROOT) -> dict[str, Any]:
    """Сверяет БД и её подпапку: сироты (есть файл, нет записи) и битые ссылки."""
    folder = exports_dir_for(db_path, root)
    refs = referenced_csv(db_path)
    known = {_norm(path) for _, path in refs}
    orphans = [
        path
        for path in _walk_files(folder, skip_dirs=(ORPHANS_DIR,))
        if _norm(path) not in known and not os.path.basename(path).startswith(REPORT_PREFIX)
    ]
    missing = [(file_id, path) for file_id, path in refs if not os.path.isfile(path)]
    outside = [(file_id, path) for file_id, path in refs
               if os.path.isfile(path) and not _is_inside(path, folder)]
    return {"folder": folder, "orphans": orphans, "missing": missing, "outside": outside,
            "referenced": len(refs), "legacy": _legacy_csv(db_path, root, refs)}


LEGACY_DIR = "_legacy"


def _legacy_csv(db_path: str, root: str, refs: list[tuple[int, str]]) -> list[str]:
    """CSV прямо в корне экспорта, на которые не ссылается ни эта, ни соседние БД."""
    if not os.path.isdir(root):
        return []
    known = {_norm(p) for _, p in refs} | _other_db_refs(db_path)
    return sorted(
        os.path.join(root, name) for name in os.listdir(root)
        if name.lower().endswith(".csv") and os.path.isfile(os.path.join(root, name))
        and _norm(os.path.join(root, name)) not in known
    )


def _other_db_refs(db_path: str) -> set[str]:
    """Нормализованные пути CSV, на которые ссылаются другие .db рядом с этой."""
    refs: set[str] = set()
    folder = os.path.dirname(os.path.abspath(db_path))
    for name in os.listdir(folder):
        other = os.path.join(folder, name)
        if not name.lower().endswith(".db") or _norm(other) == _norm(db_path):
            continue
        try:
            refs.update(_norm(p) for _, p in referenced_csv(other))
        except sqlite3.Error:
            continue
    return refs


def _migrate_outside(db_path: str, folder: str, outside: list[tuple[int, str]]) -> list[tuple[str, str, str]]:
    """Переносит CSV из старой общей папки в подпапку БД и правит files.csv_path.

    Если на файл ссылается другая БД, он копируется (оригинал остаётся ей).
    Возвращает список (откуда, куда, 'move'|'copy').
    """
    if not outside:
        return []
    shared = _other_db_refs(db_path)
    mapping: dict[str, str] = {}
    done: list[tuple[str, str, str]] = []
    os.makedirs(folder, exist_ok=True)
    for _, path in outside:
        key = _norm(path)
        if key in mapping:
            continue
        target = os.path.join(folder, os.path.basename(path))
        if os.path.exists(target) and _norm(target) != key:
            mapping[key] = target  # уже перенесён ранее
            continue
        if key in shared:
            shutil.copy2(path, target)
            action = "copy"
        else:
            shutil.move(path, target)
            action = "move"
        mapping[key] = target
        done.append((path, target, action))

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT id, csv_path FROM files WHERE csv_path IS NOT NULL AND csv_path <> ''"
        ).fetchall()
        for file_id, joined in rows:
            parts = [p.strip() for p in str(joined).split(";") if p.strip()]
            new_parts = [mapping.get(_norm(p), p) for p in parts]
            if new_parts != parts:
                connection.execute("UPDATE files SET csv_path = ? WHERE id = ?",
                                   (";".join(new_parts), file_id))
        connection.commit()
    finally:
        connection.close()
    return done


def prune_exports(db_path: str, root: str = EXPORTS_ROOT, apply: bool = False) -> dict[str, Any]:
    """При apply=True: CSV из старой общей папки переезжают в подпапку БД,
    сироты уходят в `<подпапка>/_orphans/`."""
    result = check_exports(db_path, root)
    result["moved"] = []
    result["migrated"] = []
    result["legacy_moved"] = 0
    if apply:
        result["migrated"] = _migrate_outside(db_path, result["folder"], result["outside"])
        target_dir = os.path.join(result["folder"], ORPHANS_DIR)
        for path in result["orphans"]:
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, os.path.basename(path))
            if os.path.exists(target):
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                target = os.path.join(target_dir, "%s_%s" % (stamp, os.path.basename(path)))
            shutil.move(path, target)
            result["moved"].append(target)
        # Остатки старой общей папки: после переноса заново, чтобы не тронуть только что
        # скопированные/перенесённые файлы этой БД.
        legacy = _legacy_csv(db_path, root, referenced_csv(db_path))
        if legacy:
            legacy_dir = os.path.join(root, LEGACY_DIR)
            os.makedirs(legacy_dir, exist_ok=True)
            for path in legacy:
                shutil.move(path, os.path.join(legacy_dir, os.path.basename(path)))
            result["legacy_moved"] = len(legacy)
    return result


def _dispose(path: str, base_dir: str, archive_dir: str | None) -> None:
    """Переносит файл в архив (сохраняя путь внутри base_dir) или удаляет."""
    if archive_dir is None:
        os.remove(path)
        return
    target = os.path.join(archive_dir, "exports", os.path.relpath(path, base_dir))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(path, target)


def drop_database(
    db_path: str,
    root: str = EXPORTS_ROOT,
    archive_root: str = ARCHIVE_ROOT,
    archive: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Удаляет БД вместе с её CSV: сначала CSV из БД, потом сама БД.

    CSV, лежащие вне подпапки этой БД (старая общая `data/exports`), не
    трогаются: на них могут ссылаться другие базы.
    archive=True переносит всё в `data/archive/<бд>_<время>/`, иначе удаляет.
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    folder = exports_dir_for(db_path, root)
    refs = referenced_csv(db_path)  # соединение уже закрыто — файл БД свободен

    archive_dir = None
    if archive:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = os.path.join(archive_root, "%s_%s" % (db_stem(db_path), stamp))

    result: dict[str, Any] = {
        "folder": folder, "archive_dir": archive_dir, "dry_run": dry_run,
        "csv_done": [], "csv_missing": [], "csv_foreign": [], "leftovers": [], "db": [],
    }
    seen: set[str] = set()
    for _, path in refs:
        key = _norm(path)
        if key in seen:
            continue
        seen.add(key)
        if not os.path.isfile(path):
            result["csv_missing"].append(path)
        elif not _is_inside(path, folder):
            result["csv_foreign"].append(path)
        else:
            result["csv_done"].append(path)
            if not dry_run:
                _dispose(path, folder, archive_dir)

    # Остальное в подпапке (отчёты, сироты) принадлежит только этой БД.
    if os.path.isdir(folder):
        for path in _walk_files(folder):
            if _norm(path) in seen:
                continue
            result["leftovers"].append(path)
            if not dry_run:
                _dispose(path, folder, archive_dir)
        if not dry_run:
            shutil.rmtree(folder, ignore_errors=True)

    # Только после CSV — сама БД и её служебные файлы.
    for suffix in ("",) + DB_SIDECARS:
        path = db_path + suffix
        if not os.path.isfile(path):
            continue
        result["db"].append(path)
        if dry_run:
            continue
        if archive_dir:
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(path, os.path.join(archive_dir, os.path.basename(path)))
        else:
            os.remove(path)
    return result
