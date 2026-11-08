# Этап 1. Что реализовано

Ядро без GUI: берёт папку с Word-документами, читает штамп, считает хэш,
определяет версию документа, извлекает таблицы в CSV и пишет всё в SQLite.

## Запуск

```
pip install -r requirements.txt
python main.py ВОР                 # прогон папки, результат в data/app.db
python main.py ВОР --db my.db      # другая база
python -m pytest -q tests          # тесты
python convert_doc.py КЖ СО        # .doc -> .docx, разбор штампа, лист на папку в vor_parsing_results.xlsx
```

`main.py` только вызывает `scripts/process_folder.py`. Файлы `.doc` читаются
через Microsoft Word (pywin32); без Word такой файл получает
`stamp_status = UNSUPPORTED`. Тест записи в xlsx требует, чтобы
`vor_parsing_results.xlsx` был закрыт в Excel.

## Структура

| Файл | Назначение |
|---|---|
| `core/database.py` | SQLite, таблица `files`: `init_db`, `add_file`, `get_current_by_path`, `get_by_variant_group`, `get_file_by_id`, `update_file_status`, `recalc_is_current` |
| `core/hasher.py` | SHA-256 блоками по 8192 байта, `compute_variant_group`, `process_file_entry` |
| `core/parsers/stamp_parser.py` | разбор штампа из колонтитула |
| `core/parsers/docx_parser.py` | таблицы, очистка ячеек, шапки, CSV |
| `core/doc_converter.py` | `.doc` -> `.docx` через Word |
| `scripts/process_folder.py` | сквозной прогон папки |
| `convert_doc.py` | массовый прогон папок с записью в xlsx |

## Версии документов

Документ определяется штампом, а не путём: `doc_code` + `revision` +
`revision_date` дают `variant_group`. `process_file_entry` возвращает:

- `NEW` — такого `doc_code` ещё нет;
- `ALREADY_EXISTS` — те же реквизиты и тот же хэш (копия в другой папке тоже);
- `NEW_VERSION` — новая версия; прежние версии получают `is_current = 0`;
- `NEW_VARIANT` — те же реквизиты, другой хэш; обе записи остаются текущими,
  выбирает пользователь.

## Штамп

`parse_stamp(path)` возвращает: `doc_code`, `project_code`, `section_code`,
`doc_type`, `revision`, `revision_date`, `revision_date_source`, `sheet`,
`sheets_total`, `stage`, `organization`, `object_name`, `title`,
`document_name`, `executors` (должность, ФИО, подпись, дата), `stamp_profile`,
`filename_dates`, `discrepancies`, `stamp_raw`, `stamp_status`.

- **Профили штампа:** `full` (ИСВН, три блока названий), `short` (ЭС1, один
  блок; титул отделяется по фразе «N этап строительства»), `unknown`.
- **Шифр:** пробелы вокруг дефисов убираются; тип документа может содержать
  цифры (`.В4`). Шифр без типа получает `doc_type = XN` (виртуальный тип);
  в `doc_code` `.XN` не дописывается.
- **Дата:** штамп, затем имя файла, затем дата последнего изменения файла;
  источник в `revision_date_source` (`stamp` / `filename` / `modified`).
- **Расхождения** штампа с именем файла (дата, номер «Изм.N») парсер не
  исправляет, а пишет в `discrepancies`: решает пользователь.
- **stamp_status:** `OK`, `PARTIAL`, `MISSING`, `UNSUPPORTED`.
- Для ИСВН `revision = 1` («Изм. 1, Нов.»), ТЗ приведено в соответствие.

## Таблицы и CSV

`extract_tables_from_docx` берёт таблицы через `docx2python`;
`clean_cell_text` склеивает абзацы и списки в строку без переносов;
`extract_headers` собирает шапку из нескольких строк, отбрасывает строку
нумерации и раскрывает групповые заголовки; `save_table_to_csv` пишет
`data/exports/{hash[:16]}_table_N.csv` в `utf-8-sig`, пути идут в
`files.csv_path` через `;`, статус файла становится `SAVED` (или `ERROR`).

## Тесты

49 тестов в `tests/`: хэш и четыре сценария версий, очистка ячеек, шапки, CSV,
сквозной прогон на собранном вручную docx, штамп ИСВН и ЭС1 на реальных файлах,
правила даты. Часть тестов использует реальные файлы из папки `ВОР`.

## Известные ограничения

- Групповые шапки с объединением на реальных ВОР проверены не полностью:
  стоит открыть несколько CSV в Excel.
- Короткий профиль штампа опирается на эвристику («N этап строительства»).
- После правки `extract_tables_from_docx` CSV в `data/exports` нужно
  перегенерировать (`python main.py ВОР`).
