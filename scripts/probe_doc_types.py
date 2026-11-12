"""Сводка по шапкам таблиц для папок разных типов документов (только чтение).

Использование:
    python scripts/probe_doc_types.py [--out data/exports/probes] ВОР СО КЖ

.doc конвертируются через Word во временную папку (как в пайплайне).
Для каждой папки: профиль шапки, тип по штампу, число таблиц, частоты наборов
заголовков. В консоль печатается ход работы (папки, счётчик, итог, путь к
результату), для каждой папки пишется файл `doc_types_<папка>.xlsx` с листами
«Сводка» и «Наборы заголовков»; файлы с ошибкой или без шапки перечислены на
втором листе с пометкой и причиной.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.doc_converter import read_doc_stamp_source  # noqa: E402
from core.parsers.docx_parser import extract_tables_from_docx  # noqa: E402
from core.parsers.header_profiles import parse_table  # noqa: E402
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from core.parsers.stamp_parser import parse_stamp  # noqa: E402
from scripts.report_utils import (  # noqa: E402
    MARK_ERROR, MARK_SKIPPED, Progress, list_documents, print_plan,
    print_summary, reason_of, write_workbook,
)

FIXED = ("№", "Колонок", "Файлов", "Профиль", "Пример файла")


def survey(folder: str, cache: str, progress: Progress, out_dir: Path) -> tuple[str, int, list]:
    """Обрабатывает папку, печатает сводку, пишет xlsx. Возвращает (строка итога, число, проблемы)."""
    files = list_documents(folder)
    count = len(files)
    print("\n== %s: %d файлов" % (folder, count), flush=True)
    profiles: Counter[str] = Counter()
    types: Counter[str] = Counter()
    header_sets: Counter[tuple[str, ...]] = Counter()
    table_counts: Counter[int] = Counter()
    first_samples: dict[tuple[str, ...], str] = {}
    profile_of_set: dict[tuple[str, ...], str] = {}
    problems: list[tuple[str, str, str]] = []
    for number, path in enumerate(files, 1):
        progress.step(folder, number, count, path.name)
        try:
            source = read_doc_stamp_source(str(path), cache)
            stamp = parse_stamp(source)
            types[stamp.get("doc_type") or "-"] += 1
            with numbering_fixed(source) as readable:
                tables = extract_tables_from_docx(readable)
        except Exception as error:  # noqa: BLE001
            reason = reason_of(error)
            problems.append((MARK_ERROR, path.name, reason))
            progress.note("ОШИБКА: " + reason)
            continue
        table_counts[len(tables)] += 1
        main_seen = False
        for table in tables:
            parsed = parse_table(table)
            if not any(parsed.headers):
                continue
            profiles[parsed.profile] += 1
            key = tuple(parsed.headers)
            header_sets[key] += 1
            first_samples.setdefault(key, path.name)
            profile_of_set.setdefault(key, parsed.profile)
            main_seen = True
            break  # только главная таблица файла
        if not main_seen:
            profiles["(нет шапки)"] += 1
            reason = "нет таблицы с шапкой (таблиц в файле: %d)" % len(tables)
            problems.append((MARK_SKIPPED, path.name, reason))
            progress.note("НЕ ОБРАБОТАН: " + reason)

    errors = sum(1 for mark, _, _ in problems if mark == MARK_ERROR)
    print("  тип штампа:", dict(types))
    print("  профили шапки (главная таблица):", dict(profiles))
    print("  таблиц в файле:", dict(sorted(table_counts.items())))
    print("  ошибок:", errors)
    for key, n in header_sets.most_common():
        print("  %3dx %d кол. пример: %s" % (n, len(key), first_samples[key]))
        print("       ", " ; ".join(key))

    width = max((len(k) for k in header_sets), default=0)
    summary = [["Файлов в папке", count]]
    summary += [["Тип штампа: %s" % k, v] for k, v in types.most_common()]
    summary += [["Профиль шапки: %s" % k, v] for k, v in profiles.most_common()]
    summary += [["Файлов с %d таблицами" % k, v] for k, v in sorted(table_counts.items())]
    summary += [["Ошибок", errors], ["Без шапки", len(problems) - errors]]
    sets_rows = [
        [i, len(key), n, profile_of_set[key], first_samples[key], *key]
        for i, (key, n) in enumerate(header_sets.most_common(), 1)
    ]
    result = write_workbook(out_dir / ("doc_types_%s.xlsx" % (Path(folder).name or "folder")), [
        {"title": "Сводка", "header": ["Показатель", "Значение"], "rows": summary,
         "widths": {1: 36, 2: 14}},
        {"title": "Наборы заголовков",
         "header": list(FIXED) + ["Колонка %d" % i for i in range(1, width + 1)],
         "rows": sets_rows, "problems": problems, "freeze": "F2", "widths": {5: 40}},
    ])
    line = "%s: обработано %d из %d, уникальных наборов %d, проблемных файлов %d -> %s" % (
        folder, count - len(problems), count, len(header_sets), len(problems), result)
    print(line, flush=True)
    return line, count, problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--out", default="data/exports/probes")
    args = parser.parse_args()
    out_dir = Path(args.out)

    existing = [f for f in args.folders if Path(f).is_dir()]
    print_plan("Папки", [(f, len(list_documents(f)) if f in existing else None) for f in args.folders], out_dir)
    progress = Progress(sum(len(list_documents(f)) for f in existing))
    lines: list[str] = []
    all_problems: list[tuple[str, str, str, str]] = []
    with tempfile.TemporaryDirectory() as cache:
        for index, folder in enumerate(existing, 1):
            print("\n=== Папка %d/%d: %s ===" % (index, len(existing), folder), flush=True)
            line, _, problems = survey(folder, cache, progress, out_dir)
            lines.append(line)
            all_problems += [(folder, *p) for p in problems]
    print_summary(lines, all_problems, progress.total - len(all_problems), progress.total, out_dir)


if __name__ == "__main__":
    main()
