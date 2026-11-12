"""Выгрузка и замена кода запросов Power Query в книге xlsx.

Работа с форматом DataMashup (customXml, метаданные, права, connections) выполняется
готовым пакетом pyOpenVBA (`pip install pyOpenVBA`, класс `PowerQueryWorkbook`).
Свой разбор формата в скрипте не ведётся: скрипт только переводит папку `.pq` <-> книга.

Команды (книга не должна быть открыта в Excel):
  python scripts/pq_sync.py list   <книга.xlsx>
  python scripts/pq_sync.py export <книга.xlsx> [--out папка]
  python scripts/pq_sync.py import <папка_с_pq> <книга.xlsx> [--add] [--prune] [--dry-run]
  python scripts/pq_sync.py new    <папка_с_pq> <новая_книга.xlsx> [--force]

export:  по одному файлу `<имя запроса>.pq` и `_manifest.json` (имя, файл, порядок).
         По умолчанию папка `<книга>_pq/` рядом с книгой.
import:  заменяет код запросов, у которых в папке есть .pq с тем же именем.
         --add      добавить запросы, которых в книге нет (только подключение);
         --prune    удалить из книги запросы, для которых нет .pq;
         --dry-run  только показать, что изменится;
         Книга заменяется на месте, прежняя сохраняется как `<книга>.bak.xlsx`.
new:     создаёт новую книгу (пакет формирует pyOpenVBA по пустой книге, сохранённой Excel)
         и добавляет в неё все запросы из папки. Существующий файл без --force не трогается.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import warnings
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_utils import (  # noqa: E402
    MARK_ERROR, MARK_SKIPPED, Progress, print_plan, print_summary, reason_of, write_workbook,
)

try:
    from pyopenvba import PowerQueryError, PowerQueryWorkbook
except ImportError:  # pragma: no cover
    sys.exit("ОШИБКА: не установлен pyOpenVBA. Выполните: pip install pyOpenVBA")

MANIFEST = "_manifest.json"
_BAD_FILE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class PqError(Exception):
    pass


def norm(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def for_book(text: str) -> str:
    """pyOpenVBA ставит `;` сразу после кода: если последняя строка с комментарием `//`,
    `;` уйдёт в комментарий. Перевод строки в конце это исключает."""
    return text + "\n" if "//" in text.rsplit("\n", 1)[-1] else text


def file_name_for(name: str, used: set[str]) -> str:
    base = _BAD_FILE.sub("_", name).strip(" .") or "query"
    candidate, n = base, 2
    while candidate.lower() in used:
        candidate = "%s_%d" % (base, n)
        n += 1
    used.add(candidate.lower())
    return candidate + ".pq"


def _open(xlsx: Path) -> PowerQueryWorkbook:
    try:
        book = PowerQueryWorkbook(xlsx)
    except PowerQueryError as e:
        raise PqError(str(e))
    if not book.has_queries:
        raise PqError("в книге нет запросов Power Query")
    return book


def cmd_list(xlsx: Path) -> int:
    book = _open(xlsx)
    print("Книга:", xlsx.resolve())
    for i, q in enumerate(book.queries(), 1):
        print("  %2d. %s [%s] (%d строк)" % (i, q.name, q.load_target, norm(q.formula).count("\n") + 1))
    print("Запросов: %d" % len(book.query_names()))
    return 0


def cmd_export(xlsx: Path, out: Path | None) -> int:
    out = out or xlsx.with_name(xlsx.stem + "_pq")
    book = _open(xlsx)
    queries = book.queries()
    print_plan("Книга", [(str(xlsx), len(queries))], out)
    out.mkdir(parents=True, exist_ok=True)
    progress = Progress(len(queries))
    used: set[str] = set()
    manifest, rows, problems = [], [], []
    for i, q in enumerate(queries, 1):
        progress.step("запросы", i, len(queries), q.name)
        try:
            text = norm(q.formula)
            fname = file_name_for(q.name, used)
            (out / fname).write_text(text + "\n", encoding="utf-8", newline="\n")
            manifest.append({"name": q.name, "file": fname})
            rows.append([i, q.name, fname, q.load_target, text.count("\n") + 1])
        except OSError as e:
            problems.append(("запросы", MARK_ERROR, q.name, reason_of(e)))
    (out / MANIFEST).write_text(
        json.dumps({"source": xlsx.name, "queries": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    report = write_workbook(out / "_export_report.xlsx", [{
        "title": "Запросы", "header": ["№", "Запрос", "Файл", "Загрузка", "Строк"], "rows": rows,
        "problems": [(p[1], p[2], p[3]) for p in problems], "freeze": "A2",
        "widths": {2: 36, 3: 40}}])
    print_summary(["Выгружено запросов: %d" % len(manifest), "Отчёт: %s" % report],
                  problems, len(manifest), len(queries), out)
    return 1 if problems else 0


def _read_dir(folder: Path) -> tuple[dict[str, str], list[tuple[str, str, str, str]]]:
    """Код запросов из папки: имя -> текст. Имя берётся из манифеста, иначе из имени файла."""
    names: dict[str, str] = {}
    if (folder / MANIFEST).is_file():
        for q in json.loads((folder / MANIFEST).read_text(encoding="utf-8"))["queries"]:
            names[q["file"].lower()] = q["name"]
    code, problems = {}, []
    for p in sorted(folder.glob("*.pq"), key=lambda x: x.name.lower()):
        name = names.get(p.name.lower(), p.stem)
        try:
            text = norm(p.read_text(encoding="utf-8-sig"))
            if not text:
                raise PqError("файл пуст")
            code[name] = text
        except (OSError, UnicodeDecodeError, PqError) as e:
            problems.append(("файлы", MARK_ERROR, p.name, reason_of(e)))
    return code, problems


def cmd_import(xlsx: Path, folder: Path, add: bool, prune: bool, dry: bool) -> int:
    if not folder.is_dir():
        raise PqError("нет папки %s" % folder)
    book = _open(xlsx)
    code, problems = _read_dir(folder)
    print_plan("Папка с запросами", [(str(folder), len(code) + len(problems))],
              xlsx if not dry else "(без записи, --dry-run)")
    existing = set(book.query_names())
    progress = Progress(len(code))
    rows, replaced, added, same = [], 0, 0, 0
    for i, (name, text) in enumerate(code.items(), 1):
        progress.step("запросы", i, len(code), name)
        try:
            if name in existing:
                q = book.query(name)
                if norm(q.formula) == text:
                    same += 1
                    rows.append([name, "без изменений", ""])
                else:
                    q.formula = for_book(text)
                    replaced += 1
                    rows.append([name, "заменён", ""])
            elif add:
                book.add_query(name, for_book(text))
                added += 1
                rows.append([name, "добавлен", "без настроек загрузки"])
            else:
                problems.append(("запросы", MARK_SKIPPED, name, "в книге нет такого запроса (нужен --add)"))
        except Exception as e:  # ошибка M-кода или пакета: файл не прерывает остальные
            problems.append(("запросы", MARK_ERROR, name, reason_of(e)))
    missing = [n for n in existing if n not in code]
    removed = 0
    for name in missing:
        if prune:
            if not dry:
                book.remove_query(name)
            removed += 1
            rows.append([name, "удалён", "нет .pq в папке"])
        else:
            rows.append([name, "не тронут", "нет .pq в папке"])
    lines = ["Заменено: %d, добавлено: %d, без изменений: %d, удалено: %d, не тронуто: %d" % (
        replaced, added, same, removed, len(missing) - removed)]
    if dry:
        lines.append("--dry-run: книга не изменена")
    elif replaced or added or removed:
        backup = xlsx.with_name(xlsx.stem + ".bak.xlsx")
        shutil.copy2(xlsx, backup)
        lines.append("Прежняя книга сохранена: %s" % backup.resolve())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            book.save()
        lines += ["Предупреждение пакета: %s" % w.message for w in caught]
        lines.append("Книга записана: %s" % xlsx.resolve())
    else:
        lines.append("Изменений нет, книга не перезаписана")
    report = write_workbook((folder if dry else xlsx.parent) / "_import_report.xlsx", [{
        "title": "Запросы", "header": ["Запрос", "Результат", "Примечание"], "rows": rows,
        "problems": [(p[1], p[2], p[3]) for p in problems], "widths": {1: 36, 2: 18, 3: 40}}])
    lines.append("Отчёт: %s" % report)
    print_summary(lines, problems, replaced + added + same, len(code) + len(problems), folder)
    return 1 if problems else 0


def cmd_new(folder: Path, xlsx: Path, force: bool) -> int:
    if not folder.is_dir():
        raise PqError("нет папки %s" % folder)
    if xlsx.exists() and not force:
        raise PqError("файл %s уже есть (нужен --force, чтобы перезаписать)" % xlsx)
    code, problems = _read_dir(folder)
    if not code:
        raise PqError("в папке нет .pq файлов")
    print_plan("Папка с запросами", [(str(folder), len(code) + len(problems))], xlsx)
    book = PowerQueryWorkbook.create_new(xlsx)
    progress = Progress(len(code))
    done = 0
    for i, (name, text) in enumerate(code.items(), 1):
        progress.step("запросы", i, len(code), name)
        try:
            book.add_query(name, for_book(text))
            done += 1
        except Exception as e:
            problems.append(("запросы", MARK_ERROR, name, reason_of(e)))
    book.save()
    check = PowerQueryWorkbook(xlsx)  # проверка: книга читается обратно
    if len(check.query_names()) != done:
        raise PqError("после записи в книге %d запросов вместо %d" % (len(check.query_names()), done))
    lines = ["Создана книга с запросами: %d (только подключения)" % done, "Книга: %s" % xlsx.resolve()]
    print_summary(lines, problems, done, len(code) + len(problems), folder)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Выгрузка и замена запросов Power Query в xlsx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list")
    s.add_argument("xlsx", type=Path)
    s = sub.add_parser("export")
    s.add_argument("xlsx", type=Path)
    s.add_argument("--out", type=Path)
    s = sub.add_parser("import")
    s.add_argument("folder", type=Path)
    s.add_argument("xlsx", type=Path)
    s.add_argument("--add", action="store_true")
    s.add_argument("--prune", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("new")
    s.add_argument("folder", type=Path)
    s.add_argument("xlsx", type=Path)
    s.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            return cmd_new(a.folder, a.xlsx, a.force)
        if not a.xlsx.is_file():
            raise PqError("нет файла %s" % a.xlsx)
        if a.cmd == "list":
            return cmd_list(a.xlsx)
        if a.cmd == "export":
            return cmd_export(a.xlsx, a.out)
        return cmd_import(a.xlsx, a.folder, a.add, a.prune, a.dry_run)
    except (PqError, PowerQueryError, zipfile.BadZipFile, PermissionError) as e:
        print("ОШИБКА:", reason_of(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
