"""Экспорт наборов заголовков главной таблицы в Excel по типам документов.

Использование:
    python scripts/export_headers.py [--out data/exports/headers] [ВОР КЖ СВОР СО]

Для каждой папки создаётся файл `headers_<папка>.xlsx`. Одинаковые наборы
заголовков внутри типа не дублируются: одна строка на уникальный набор,
в ней число файлов, профиль, пример файла и заголовки по столбцам.
Файлы с ошибкой и файлы без таблицы с шапкой перечислены в том же листе
ниже наборов, с пометкой «ОШИБКА» или «НЕ ОБРАБОТАН».
Ход работы (папки, счётчик файлов, итог, путь к результату) печатается в консоль.

Кроме разбора через `parse_table` каждый файл прогоняется через основной алгоритм
(`process_folder._process_one`, временная БД, рабочая БД не затрагивается). В xlsx три листа:
наборы по способу скрипта (лист с именем папки), наборы основного алгоритма
(по таблице `schemas`) и «Сравнение» с файлами, где результаты расходятся.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from core import database  # noqa: E402
from core.doc_converter import read_doc_stamp_source  # noqa: E402
from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.header_profiles import parse_table  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from scripts import process_folder  # noqa: E402

DEFAULT_FOLDERS = ("ВОР", "КЖ", "СВОР", "СО")
SUPPORTED = (".doc", ".docx")
FIXED = ("№", "Колонок", "Файлов", "Профиль", "Пример файла")
MARK_ERROR = "ОШИБКА"
MARK_SKIPPED = "НЕ ОБРАБОТАН"


def list_files(folder: str) -> list[Path]:
    return sorted(
        p for p in Path(folder).iterdir()
        if p.suffix.lower() in SUPPORTED and not p.name.startswith("~$")
    )


def main_algorithm(path: Path, connection, exports_dir: str) -> dict:
    """Прогоняет файл через основной алгоритм (`process_folder._process_one`) во временной БД.

    Возвращает {headers, normalized, schema_hash, doc_type, status, error}.
    Заголовки читаются из таблицы `schemas`, то есть ровно так, как их сохранил алгоритм.
    """
    row = process_folder._process_one(str(path), connection, exports_dir)
    document = database.get_file_by_id(connection, row["file_id"]) or {}
    schema_hash = document.get("schema_hash")
    schema = database.get_schema(connection, schema_hash) if schema_hash else None
    return {
        "headers": tuple(schema["raw_headers"]) if schema else (),
        "normalized": tuple(schema["normalized_headers"]) if schema else (),
        "schema_hash": schema_hash or "",
        "doc_type": document.get("doc_type") or "",
        "status": row["status"],
        "error": "",
    }


def collect(
    folder: str, cache: str, progress: dict, connection=None, exports_dir: str = ""
) -> tuple[dict, list[tuple[str, str, str]], dict, dict]:
    """Возвращает (наборы по `parse_table`, проблемные файлы, наборы основного алгоритма, по-файлово).

    Наборы: {набор заголовков: {profile, count, sample}}. Проблемный файл: (пометка, имя, причина).
    По-файлово: {имя: {"script": заголовки скрипта, "main": результат основного алгоритма}}.
    progress: {"done": уже просмотрено файлов, "total": всего во всех папках}.
    Без `connection` основной алгоритм не запускается.
    """
    files = list_files(folder)
    total = len(files)
    sets: dict[tuple[str, ...], dict] = {}
    main_sets: dict[tuple[str, ...], dict] = {}
    per_file: dict[str, dict] = {}
    problems: list[tuple[str, str, str]] = []
    for number, path in enumerate(files, 1):
        progress["done"] += 1
        print("  [%s] %d/%d (всего %d/%d) %s" % (
            folder, number, total, progress["done"], progress["total"], path.name), flush=True)
        try:
            source = read_doc_stamp_source(str(path), cache)
            with numbering_fixed(source) as readable:
                tables = extract_tables_from_docx(readable)
        except Exception as error:  # noqa: BLE001
            reason = "%s: %s" % (type(error).__name__, str(error)[:150])
            problems.append((MARK_ERROR, path.name, reason))
            print("      ОШИБКА:", reason, flush=True)
            continue
        found = False
        for table in tables:
            parsed = parse_table(table)
            if not any(parsed.headers):
                continue
            key = tuple(parsed.headers)
            entry = sets.setdefault(
                key, {"profile": parsed.profile, "count": 0, "sample": path.name}
            )
            entry["count"] += 1
            per_file[path.name] = {"script": key, "main": None}
            found = True
            break  # только главная таблица файла
        if not found:
            reason = "нет таблицы с шапкой (таблиц в файле: %d)" % len(tables)
            problems.append((MARK_SKIPPED, path.name, reason))
            print("      НЕ ОБРАБОТАН:", reason, flush=True)
        if connection is None:
            continue
        # Тот же файл через основной алгоритм: для сравнения с результатом выше.
        entry_main = per_file.setdefault(path.name, {"script": (), "main": None})
        try:
            result = main_algorithm(path, connection, exports_dir)
        except Exception as error:  # noqa: BLE001
            result = {
                "headers": (), "normalized": (), "schema_hash": "", "doc_type": "",
                "status": "ERROR", "error": "%s: %s" % (type(error).__name__, str(error)[:150]),
            }
            print("      ОСНОВНОЙ АЛГОРИТМ, ОШИБКА:", result["error"], flush=True)
        entry_main["main"] = result
        if result["headers"]:
            info = main_sets.setdefault(result["headers"], {
                "profile": result["doc_type"], "count": 0, "sample": path.name,
                "normalized": result["normalized"],
            })
            info["count"] += 1
    return sets, problems, main_sets, per_file


def compare(per_file: dict) -> tuple[list[list], int]:
    """Строки сравнения (файл, причина, заголовки скрипта, основного алгоритма, нормализованные)
    только для файлов с расхождением и число совпавших файлов."""
    diff: list[list] = []
    same = 0
    for name, item in sorted(per_file.items()):
        main = item["main"]
        if main is None:
            continue
        script = item["script"]
        if main["error"]:
            reason = "основной алгоритм: " + main["error"]
        elif main["status"] != "SAVED":
            reason = "основной алгоритм: статус %s" % main["status"]
        elif script != main["headers"]:
            reason = "заголовки различаются"
        else:
            same += 1
            continue
        diff.append([name, reason, " | ".join(script), " | ".join(main["headers"]),
                     " | ".join(main["normalized"])])
    return diff, same


def fill_compare(ws, per_file: dict) -> None:
    diff, same = compare(per_file)
    ws.append(["Сравнение: способ скрипта (parse_table) и основной алгоритм (process_folder -> БД)"])
    ws.cell(row=1, column=1).font = Font(bold=True)
    ws.append(["Файлов сравнено", same + len(diff)])
    ws.append(["Совпало", same])
    ws.append(["Расхождений", len(diff)])
    ws.append([])
    if not diff:
        ws.append(["Расхождений нет"])
    else:
        ws.append(["Файл", "Причина", "Заголовки скрипта", "Заголовки основного алгоритма",
                   "Нормализованные (основной)"])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        fill = PatternFill("solid", fgColor="FFC7CE")
        for row in diff:
            ws.append(row)
            for cell in ws[ws.max_row][:5]:
                cell.fill = fill
    for index, width in enumerate((50, 40, 60, 60, 60), 1):
        ws.column_dimensions[get_column_letter(index)].width = width


def write_xlsx(
    folder: str, sets: dict, problems: list, out_dir: Path,
    main_sets: dict | None = None, per_file: dict | None = None,
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = folder[:31]
    fill_sheet(ws, sets, problems)
    if main_sets is not None:
        fill_sheet(wb.create_sheet("Основной алгоритм"), main_sets, [])
        fill_compare(wb.create_sheet("Сравнение"), per_file or {})
    target = out_dir / ("headers_%s.xlsx" % folder)
    wb.save(target)  # файл должен быть закрыт в Excel
    return target


def fill_sheet(ws, sets: dict, problems: list) -> None:
    width = max((len(k) for k in sets), default=0)
    ws.append(list(FIXED) + ["Колонка %d" % i for i in range(1, width + 1)])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ordered = sorted(sets.items(), key=lambda kv: (-kv[1]["count"], len(kv[0])))
    for number, (key, info) in enumerate(ordered, 1):
        ws.append([number, len(key), info["count"], info["profile"], info["sample"], *key])
    if problems:
        ws.append([])
        ws.append(["Файлы с ошибкой или без обработки: %d" % len(problems)])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.append(["Пометка", "Файл", "Причина"])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        fill = PatternFill("solid", fgColor="FFC7CE")
        for mark, name, reason in problems:
            ws.append([mark, name, reason])
            for cell in ws[ws.max_row][:3]:
                cell.fill = fill
    ws.freeze_panes = "F2"
    for index in range(1, len(FIXED) + width + 1):
        ws.column_dimensions[get_column_letter(index)].width = 40 if index == 5 else 22


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="*", default=list(DEFAULT_FOLDERS))
    parser.add_argument("--out", default="data/exports/headers")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = [f for f in args.folders if Path(f).is_dir()]
    print("Папки к обработке:")
    for folder in args.folders:
        if folder in existing:
            print("  %s (файлов: %d)" % (folder, len(list_files(folder))))
        else:
            print("  %s - НЕТ ТАКОЙ ПАПКИ, пропуск" % folder)
    print("Папка результата:", out_dir.resolve(), flush=True)

    summary: list[str] = []
    all_problems: list[tuple[str, str, str, str]] = []
    progress = {"done": 0, "total": sum(len(list_files(f)) for f in existing)}
    with tempfile.TemporaryDirectory() as cache:
        # Основной алгоритм работает во временной БД; рабочая data/app.db не трогается.
        process_folder.CONVERTED_DIR = cache
        exports_dir = str(Path(cache) / "exports")
        Path(exports_dir).mkdir()
        connection = database.init_db(str(Path(cache) / "check.db"))
        try:
            for index, folder in enumerate(existing, 1):
                print("\n=== Папка %d/%d: %s ===" % (index, len(existing), folder), flush=True)
                count = len(list_files(folder))
                sets, problems, main_sets, per_file = collect(
                    folder, cache, progress, connection, exports_dir)
                diff, same = compare(per_file)
                try:
                    target = write_xlsx(folder, sets, problems, out_dir, main_sets, per_file)
                    result = str(target.resolve())
                except PermissionError:
                    result = "НЕ ЗАПИСАН (файл открыт в Excel?)"
                line = ("%s: обработано %d из %d, уникальных наборов %d (основной алгоритм %d), "
                        "расхождений со скриптом %d, проблемных файлов %d -> %s") % (
                    folder, count - len(problems), count, len(sets), len(main_sets),
                    len(diff), len(problems), result)
                print(line, flush=True)
                summary.append(line)
                all_problems += [(folder, *p) for p in problems]
        finally:
            connection.close()

    print("\n=== Итог ===")
    print("Обработано без проблем: %d из %d файлов" % (
        progress["total"] - len(all_problems), progress["total"]))
    print("Папка с результатом:", out_dir.resolve())
    for line in summary:
        print(line)
    if all_problems:
        print("Проблемные файлы:")
        for folder, mark, name, reason in all_problems:
            print("  [%s] %s: %s - %s" % (folder, mark, name, reason))
    else:
        print("Проблемных файлов нет.")


if __name__ == "__main__":
    main()
