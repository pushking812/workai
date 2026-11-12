"""Сквозной прогон папки: штамп → хэш/версия → запись в SQLite (Этап 1.5).

Запуск:
    python -m scripts.process_folder ВОР

Для каждого документа папки разбирается штамп, считается SHA-256,
определяется, новый это документ / новая версия / второй вариант, и всё
пишется в `data/app.db`. В конце печатается таблица со всеми реквизитами
штампа.
Кроме TSV пишется `_report_<папка>.xlsx`; ход работы и итог - как в остальных
скриптах (см. scripts/README.md), проблемные файлы перечислены с причиной.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from core import database, exports
from core.doc_converter import is_doc_file, read_doc_stamp_source
from core.hasher import process_file_entry
from core.parsers.docx_parser import extract_tables_from_docx, save_table_to_csv
from core.parsers.header_profiles import parse_table
from core.parsers.numbering_fix import numbering_fixed
from core.parsers.stamp_parser import parse_stamp
from core.statuses import FileStatus
from core.transformer.schema_analyzer import analyze_and_save_schema

CONVERTED_DIR = os.path.join("data", "converted")
EXPORTS_DIR = os.path.join("data", "exports")
SUPPORTED = (".docx", ".doc")
STATUS_SAVED = FileStatus.SAVED.value
STATUS_ERROR = FileStatus.ERROR.value


def collect_documents(folder: str) -> list[str]:
    """Документы Word в папке (без вложенных папок), по алфавиту."""
    paths = [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in SUPPORTED
        and os.path.isfile(os.path.join(folder, name))
    ]
    return sorted(paths, key=lambda path: os.path.basename(path).lower())


def export_tables(
    source_path: str, file_hash: str, exports_dir: str, connection=None
) -> str:
    """Сохраняет таблицы документа в CSV и возвращает пути через `;`.

    С `connection` схема первой таблицы с заголовками пишется в БД
    (`files.schema_hash` у файла одна, по главной таблице документа).
    """
    paths: list[str] = []
    schema_done = False
    first_headers: list | None = None
    first_parsed = None
    try:
        with numbering_fixed(source_path) as readable_path:
            tables = extract_tables_from_docx(readable_path)
    except Exception:  # noqa: BLE001
        return ""
    for index, table in enumerate(tables, start=1):
        if not table:
            continue
        parsed = parse_table(table, like=first_parsed)
        if any(parsed.headers):
            if first_headers is None:
                first_headers = list(parsed.headers)
                first_parsed = parsed
            elif list(parsed.headers) != first_headers:
                # Следующая таблица с другой шапкой не обрабатывается.
                continue
        if connection is not None and not schema_done and any(parsed.headers):
            analyze_and_save_schema(connection, parsed.headers, file_hash)
            if parsed.stage_codes:
                # Шифры П/Р из шапки СВОР уходят в метаданные файла.
                database.update_file_meta(
                    connection, file_hash, {"stage_codes": parsed.stage_codes}
                )
            schema_done = True
        if connection is not None and parsed.number_issues:
            # Скобка в `№ п/п` — сбой разбора: файл помечается как проблемный.
            database.update_file_meta(
                connection, file_hash, {"number_issues": parsed.number_issues[:20]}
            )
        target = os.path.join(exports_dir, "%s_table_%d.csv" % (file_hash[:16], index))
        # Таблица-продолжение без шапки: пустую строку заголовков не пишем.
        csv_headers = parsed.headers if any(parsed.headers) else None
        paths.append(save_table_to_csv(parsed.rows, target, headers=csv_headers))
    return ";".join(paths)


def _process_one(path: str, connection, exports_dir: str) -> dict:
    """Один документ: штамп, хэш/версия, запись в БД, CSV. Возвращает строку отчёта."""
    stamp_path = read_doc_stamp_source(path, CONVERTED_DIR)
    stamp = parse_stamp(stamp_path)
    if is_doc_file(path) and stamp_path == path:
        # Word недоступен: без конвертации штамп не прочитать.
        stamp["stamp_status"] = "UNSUPPORTED"
    result = process_file_entry(path, connection, stamp=stamp)

    csv_path = export_tables(stamp_path, result["hash"], exports_dir, connection)
    document = database.get_file_by_id(connection, result["file_id"]) or {}
    if csv_path:
        database.update_file_status(connection, result["file_id"], STATUS_SAVED, csv_path)
    else:
        database.update_file_status(
            connection,
            result["file_id"],
            STATUS_ERROR,
            error_message="таблицы не извлечены",
        )
    return {
        **stamp,
        **result,
        "file": os.path.basename(path),
        "status": STATUS_SAVED if csv_path else STATUS_ERROR,
        "csv_path": csv_path,
        "variant_group": document.get("variant_group"),
        "stage_codes": json.loads(document.get("meta_json") or "{}").get("stage_codes", {}),
    }


def process_folder(
    folder: str,
    db_path: str | None = None,
    progress: bool = False,
    errors: list | None = None,
) -> list[dict]:
    """Прогоняет папку через пайплайн и возвращает строки для таблицы.

    Без `errors` исключение при разборе файла прерывает прогон (как раньше).
    Если передан список, файл с исключением не прерывает прогон: в список
    добавляется (имя файла, причина), в строки он не попадает.
    """
    connection = database.init_db(db_path)
    exports_dir = exports.exports_dir_for(db_path or database.DB_PATH, EXPORTS_DIR)
    rows: list[dict] = []
    try:
        documents = collect_documents(folder)
        for number, path in enumerate(documents, start=1):
            if progress:
                print("[%d/%d] %s ..." % (number, len(documents), os.path.basename(path)),
                      end=" ", file=sys.stderr, flush=True)
            try:
                row = _process_one(path, connection, exports_dir)
            except Exception as error:  # noqa: BLE001
                if errors is None:
                    raise
                errors.append((os.path.basename(path), "%s: %s" % (type(error).__name__, str(error)[:150])))
                if progress:
                    print("ОШИБКА: %s" % errors[-1][1], file=sys.stderr, flush=True)
                continue
            rows.append(row)
            if progress:
                csv_path = row["csv_path"]
                print("%s, CSV: %d" % (row["result"], len(csv_path.split(";")) if csv_path else 0),
                      file=sys.stderr, flush=True)
    finally:
        connection.close()
    return rows


HEADER = (
    "файл",
    "штамп",
    "статус",
    "шифр",
    "проект",
    "раздел",
    "тип",
    "изм.",
    "дата",
    "лист",
    "листов",
    "результат",
    "текущая",
    "id",
    "csv",
    "шифр П",
    "шифр Р",
)


def _row_values(row: dict) -> tuple:
    """Значения одной строки в порядке HEADER (общие для TSV и xlsx)."""
    return (
        row["file"],
        row["stamp_status"],
        row["status"],
        row["doc_code"] or "-",
        row["project_code"] or "-",
        row["section_code"] or "-",
        row["doc_type"] or "-",
        row["revision"],
        row["revision_date"] or "-",
        row["sheet"] if row["sheet"] is not None else "-",
        row["sheets_total"] if row["sheets_total"] is not None else "-",
        row["result"],
        row["is_current"],
        row["file_id"],
        len(row["csv_path"].split(";")) if row["csv_path"] else 0,
        (row.get("stage_codes") or {}).get("П", "-"),
        (row.get("stage_codes") or {}).get("Р", "-"),
    )


def format_rows(rows: list[dict]) -> str:
    """Таблица реквизитов штампа в текстовом виде."""
    lines = ["\t".join(HEADER)]
    for row in rows:
        lines.append("\t".join(str(value) for value in _row_values(row)))
    return "\n".join(lines)


def collect_problems(rows: list[dict], errors: list) -> list[tuple[str, str, str]]:
    """Файлы с ошибкой или с неполным штампом: (пометка, файл, причина)."""
    problems = [("ОШИБКА", name, reason) for name, reason in errors]
    for row in rows:
        if row["status"] == STATUS_ERROR:
            problems.append(("ОШИБКА", row["file"], "таблицы не извлечены"))
        if row["stamp_status"] != "OK":
            problems.append(("ШТАМП НЕ ПОЛНЫЙ", row["file"], "stamp_status = %s" % row["stamp_status"]))
    return problems


def write_report_xlsx(rows: list[dict], problems: list, path: str) -> str:
    """Тот же отчёт по штампам в xlsx, ниже - проблемные файлы с причиной."""
    from scripts.report_utils import write_workbook

    sheet = {
        "title": "Штампы",
        "header": list(HEADER),
        "rows": [list(_row_values(row)) for row in rows],
        "problems": problems,
        "freeze": "B2",
        "widths": {1: 48},
    }
    return write_workbook(path, [sheet])


def run_maintenance(args: argparse.Namespace, db_path: str) -> int:
    """--prune и --drop-db: обслуживание связки «БД -> папка CSV»."""
    if not os.path.isfile(db_path):
        print("нет БД: " + db_path, file=sys.stderr)
        return 2
    if args.prune and args.drop_db:
        print("--prune и --drop-db вместе не используются", file=sys.stderr)
        return 2

    if args.prune:
        result = exports.prune_exports(db_path, EXPORTS_DIR, apply=args.apply)
        print("Папка CSV: %s (в БД ссылок: %d)" % (result["folder"], result["referenced"]))
        print("Сироты (CSV без записи в БД): %d" % len(result["orphans"]))
        for path in result["orphans"]:
            print("  " + path)
        print("Битые ссылки (CSV в БД есть, файла нет): %d" % len(result["missing"]))
        for file_id, path in result["missing"]:
            print("  id %d: %s" % (file_id, path))
        if result["outside"]:
            print("CSV этой БД вне её папки (старая общая папка): %d" % len(result["outside"]))
        if result["legacy"]:
            print("CSV в корне %s, не нужные ни одной БД рядом: %d" % (EXPORTS_DIR, len(result["legacy"])))
        if args.apply:
            if result["legacy_moved"]:
                print("Остатки старой общей папки перенесены в %s: %d"
                      % (os.path.join(EXPORTS_DIR, exports.LEGACY_DIR), result["legacy_moved"]))
            copies = sum(1 for _, _, a in result["migrated"] if a == "copy")
            print("Перенесено в папку БД: %d (из них скопировано, т.к. нужны другой БД: %d)"
                  % (len(result["migrated"]), copies))
            print("Перенесено в _orphans: %d" % len(result["moved"]))
        elif result["orphans"] or result["outside"] or result["legacy"]:
            print("Ничего не перенесено; для переноса добавьте --apply")
        return 0

    result = exports.drop_database(
        db_path, EXPORTS_DIR, archive=not args.no_archive, dry_run=args.dry_run
    )
    prefix = "[пробный запуск] " if args.dry_run else ""
    action = "в архив" if result["archive_dir"] else "удалено"
    print("%sCSV из БД %s: %d" % (prefix, action, len(result["csv_done"])))
    print("%sПрочие файлы папки %s: %d" % (prefix, action, len(result["leftovers"])))
    if result["csv_missing"]:
        print("%sCSV из БД уже нет на диске: %d" % (prefix, len(result["csv_missing"])))
    if result["csv_foreign"]:
        print("%sНе тронуты CSV вне папки этой БД (могут быть нужны другим базам): %d"
              % (prefix, len(result["csv_foreign"])))
    print("%sБД %s: %s" % (prefix, action, ", ".join(result["db"]) or "-"))
    if result["archive_dir"] and not args.dry_run:
        print("Архив: " + result["archive_dir"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор штампов папки в БД")
    parser.add_argument("folder", nargs="?", default="ВОР", help="папка с документами")
    parser.add_argument("--db", default=None, help="путь к файлу БД")
    parser.add_argument("--verbose", action="store_true",
                        help="напечатать таблицу реквизитов штампа в stdout")
    parser.add_argument("--prune", action="store_true",
                        help="сверить БД и её папку CSV, показать сирот и битые ссылки (папка не обрабатывается)")
    parser.add_argument("--apply", action="store_true",
                        help="вместе с --prune: перенести сирот в _orphans/")
    parser.add_argument("--drop-db", action="store_true",
                        help="удалить БД: сначала её CSV, потом сам файл БД (по умолчанию — в архив data/archive)")
    parser.add_argument("--no-archive", action="store_true",
                        help="вместе с --drop-db: удалить насовсем, без архива")
    parser.add_argument("--dry-run", action="store_true",
                        help="вместе с --drop-db: только показать, что будет сделано")
    args = parser.parse_args(argv)

    db_path = args.db or database.DB_PATH
    if args.prune or args.drop_db:
        return run_maintenance(args, db_path)

    if not os.path.isdir(args.folder):
        print("нет папки: " + args.folder, file=sys.stderr)
        return 2

    exports_dir = exports.exports_dir_for(db_path, EXPORTS_DIR)
    # Ход работы (папка, счётчик файлов) идёт в stderr, итог - в stdout.
    print("Папка к обработке:\n  %s (файлов: %d)" % (args.folder, len(collect_documents(args.folder))),
          file=sys.stderr)
    print("БД: %s" % os.path.abspath(db_path), file=sys.stderr)
    print("Папка результата (CSV и отчёты): %s" % os.path.abspath(exports_dir), file=sys.stderr, flush=True)

    failed: list[tuple[str, str]] = []
    rows = process_folder(args.folder, args.db, progress=True, errors=failed)

    os.makedirs(exports_dir, exist_ok=True)
    base = "_report_%s" % os.path.basename(os.path.abspath(args.folder))
    report_path = os.path.join(exports_dir, base + ".tsv")
    with open(report_path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(format_rows(rows))
    problems = collect_problems(rows, failed)
    xlsx_result = write_report_xlsx(rows, problems, os.path.join(exports_dir, base + ".xlsx"))
    if args.verbose:
        print(format_rows(rows))

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    errors = [row["file"] for row in rows if row["status"] == STATUS_ERROR] + [name for name, _ in failed]
    total = len(rows) + len(failed)
    print("Файлов: %d (%s)" % (len(rows), ", ".join("%s: %d" % item for item in sorted(counts.items()))))
    print("Обработано: %d из %d" % (len(rows) - sum(1 for r in rows if r["status"] == STATUS_ERROR), total))
    print("CSV: %s" % exports_dir)
    print("Отчёт по штампам: %s" % report_path)
    print("Отчёт по штампам (xlsx): %s" % xlsx_result)
    if errors:
        print("Ошибки (%d): %s" % (len(errors), "; ".join(errors)))
    for mark, name, reason in problems:
        print("  %s: %s - %s" % (mark, name, reason))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
