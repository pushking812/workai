"""Сквозной прогон папки: штамп → хэш/версия → запись в SQLite (Этап 1.5).

Запуск:
    python -m scripts.process_folder ВОР

Для каждого документа папки разбирается штамп, считается SHA-256,
определяется, новый это документ / новая версия / второй вариант, и всё
пишется в `data/app.db`. В конце печатается таблица со всеми реквизитами
штампа.
"""

from __future__ import annotations

import argparse
import os
import sys

from core import database
from core.doc_converter import is_doc_file, read_doc_stamp_source
from core.hasher import process_file_entry
from core.parsers.docx_parser import extract_tables_from_docx, save_table_to_csv
from core.parsers.header_profiles import parse_table
from core.parsers.stamp_parser import parse_stamp

CONVERTED_DIR = os.path.join("data", "converted")
EXPORTS_DIR = os.path.join("data", "exports")
SUPPORTED = (".docx", ".doc")
STATUS_SAVED = "SAVED"
STATUS_ERROR = "ERROR"


def collect_documents(folder: str) -> list[str]:
    """Документы Word в папке (без вложенных папок), по алфавиту."""
    paths = [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in SUPPORTED
        and os.path.isfile(os.path.join(folder, name))
    ]
    return sorted(paths, key=lambda path: os.path.basename(path).lower())


def export_tables(source_path: str, file_hash: str) -> str:
    """Сохраняет таблицы документа в CSV и возвращает пути через `;`."""
    paths: list[str] = []
    try:
        tables = extract_tables_from_docx(source_path)
    except Exception:  # noqa: BLE001
        return ""
    for index, table in enumerate(tables, start=1):
        if not table:
            continue
        parsed = parse_table(table)
        target = os.path.join(EXPORTS_DIR, "%s_table_%d.csv" % (file_hash[:16], index))
        paths.append(save_table_to_csv(parsed.rows, target, headers=parsed.headers))
    return ";".join(paths)


def process_folder(folder: str, db_path: str | None = None) -> list[dict]:
    """Прогоняет папку через пайплайн и возвращает строки для таблицы."""
    connection = database.init_db(db_path)
    rows: list[dict] = []
    try:
        for path in collect_documents(folder):
            stamp_path = read_doc_stamp_source(path, CONVERTED_DIR)
            stamp = parse_stamp(stamp_path)
            if is_doc_file(path) and stamp_path == path:
                # Word недоступен: без конвертации штамп не прочитать.
                stamp["stamp_status"] = "UNSUPPORTED"
            result = process_file_entry(path, connection, stamp=stamp)

            csv_path = export_tables(stamp_path, result["hash"])
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
            rows.append(
                {
                    **stamp,
                    **result,
                    "file": os.path.basename(path),
                    "status": STATUS_SAVED if csv_path else STATUS_ERROR,
                    "csv_path": csv_path,
                    "variant_group": document.get("variant_group"),
                }
            )
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
)


def format_rows(rows: list[dict]) -> str:
    """Таблица реквизитов штампа в текстовом виде."""
    lines = ["\t".join(HEADER)]
    for row in rows:
        lines.append(
            "\t".join(
                str(value)
                for value in (
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
                )
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор штампов папки в БД")
    parser.add_argument("folder", nargs="?", default="ВОР", help="папка с документами")
    parser.add_argument("--db", default=None, help="путь к файлу БД")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.folder):
        print("нет папки: " + args.folder, file=sys.stderr)
        return 2

    rows = process_folder(args.folder, args.db)
    print(format_rows(rows))
    print("\nвсего: %d" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
