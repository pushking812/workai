# Тесты проекта

Запуск из корня проекта, из venv (`%TEMP%\workai_venv`), без ключа `-I` (с ним пакеты проекта не находятся):

    $env:PYTHONUTF8=1; & $env:TEMP\workai_venv\Scripts\python.exe -m pytest -q

Один файл: `... -m pytest -q tests/test_so_share.py`. Последний полный прогон: 338 прошли, 2 пропущены (нет эталона `АПТ` и СВОР ЭС2 в `test_numbering_fix.py`). После правки мер модели ВОР+СО (2026-11-15) полный прогон не повторялся, см. `docs/backlog.md`.

Excel и Word тесты не запускают: обращение к ним подменяется. Часть тестов читает реальные документы из `РД/` (поиск по имени); если файла нет, тест пропускается или падает с понятным сообщением. Не удаляйте такие тесты, чините пути.

## Что чем покрыто

### Парсер документов и штамп
- `test_docx_parser.py` — таблицы DOCX, шапки, CSV, сквозной `process_folder`.
- `test_stamp_parser.py`, `test_stamp_dates.py`, `test_latest_revision.py`, `test_filename_date_rule.py` — штамп, дата выпуска, номер изменения, дата в имени файла.
- `test_header_profiles.py`, `test_continuation_headers.py`, `test_no_header_table.py`, `test_ditto.py`, `test_number_clean.py`, `test_svor_headers.py` — профили шапок, продолжение таблиц, `- // -`, очистка номеров, СВОР.
- `test_numbering_fix.py`, `test_numbering_shared_abstract.py` — автонумерация Word.
- `test_doc_types.py`, `test_type_aliases.py` — тип документа по штампу и имени.

### База, справочник заголовков, сопоставление
- `test_schemas_db.py`, `test_schema_hash.py`, `test_header_synonyms.py`, `test_synonyms_v4.py` … `test_synonyms_v7.py`, `test_header_decisions.py` — схемы, синонимы заголовков и миграции.
- `test_exact_match.py`, `test_fuzzy_match.py` — точное и нечёткое сопоставление заголовков.
- `test_hasher.py`, `test_registrar.py`, `test_exports.py`, `test_config.py` — хэши и версии, регистрация файлов, выгрузка БД в CSV, настройки.

### Поиск файлов, комплекты, задачи, интерфейс
- `test_scanner.py`, `test_scanner_lookalikes.py`, `test_folder_filters.py`, `test_search_manager.py` — поиск файлов.
- `test_kits.py`, `test_kits_cipher.py`, `test_kits_homoglyph.py`, `test_ambiguous_versions.py` — комплекты и шифры.
- `test_task_manager.py`, `test_controller.py`, `test_webview_api.py` — очередь задач, API-слой и мост PyWebView.

### Power Query и книга ВОР+СО
- `test_query_builder.py`, `test_query_kits.py`, `test_vor_so_build.py` — кнопка «Сформировать запросы» (по типам документов и режим ВОР+СО).
- `test_so_template.py`, `test_vor_so_template.py`, `test_template_dates.py` — структура шаблонов СО и ВОР+СО, формат `ДатаИзм`.
- `test_so_allocation.py` — эталонный алгоритм распределения объёма СО (`core/so_allocation.py`): допуск 0,5%, режимы связи, случаи СОУЭ 1 и 2.
- `test_so_share.py`, `test_key_without_date.py`, `test_name_match.py`, `test_shift_hint.py`, `test_so_collapse_label.py`, `test_spec_in_name.py` — тексты запросов `.pq` и правила в них: доля СО, ключ с датой и без неё, связь по наименованию, подсказка о сдвиге ссылки, метка примечания при склейке СО, позиции СО в наименовании ВОР.
- `test_excel_refresh.py` — автообновление книг (`core/excel_refresh.py`), Excel подменяется.
- `test_reconcile_report_api.py` — кнопка «Отчет ВОР+СО» (`Controller.reconcile_report`), скрипт отчёта подменяется.

## Чего нет
- Нет тестов для `scripts/make_reconcile.py`, `reconcile_totals.py`, `reconcile_to_xlsx.py` (в бэклоге).
- Запросы `.pq` проверяются по тексту и на синтетике; настоящее обновление в Excel делают скрипты `scripts/pq_refresh_check.ps1`, `scripts/run_kit_check.py`, а не pytest.
- Меры модели ВОР+СО (DAX) тестами не проверяются: их применяет `scripts/apply_model_measures.ps1`, проверка в Excel вручную.
