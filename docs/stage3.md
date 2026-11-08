# Этап 3. Поиск файлов и фоновые задачи

Бэкенд для GUI без самого интерфейса: поиск `.docx`/`.doc` в потоках,
регистрация найденных файлов, фоновое сохранение и подготовка. Интерфейс
вызывает только `api/controller.py`.

## Структура

| Файл | Назначение |
|---|---|
| `core/statuses.py` | `FileStatus` (хранится в `files.status`: SAVED, PROCESSING, NEEDS_MAPPING, READY, ERROR) и `UiStatus` (FOUND, EXISTS, VARIANTS — только для отрисовки, в БД не пишутся) |
| `core/search/scanner.py` | `scan_files(dirs, mask, should_stop)` — генератор путей `.docx` и `.doc` |
| `core/search/manager.py` | `SearchManager`: `start_search(dirs, mask, on_file)`, `stop_search`, `wait`, `get_status`, `get_instance`. `on_file` вызывается в потоке поиска, ошибки собираются в `errors` |
| `core/search/registrar.py` | `FileRegistrar(db_path, stamp_reader)` — обработчик `on_file`: читает штамп, определяет версию; соединение SQLite открывается на каждый файл. NEW и NEW_VERSION → FOUND, ALREADY_EXISTS → EXISTS, NEW_VARIANT → VARIANTS |
| `core/search/tasks.py` | `TaskManager(db_path, saver)`: `save_files`, `prepare_files`, `stop`, `wait`, `get_status`. Сохранение по умолчанию — `export_tables` из `scripts/process_folder.py` |
| `api/controller.py` | `Controller` и модульные функции `start_search`, `stop_search`, `get_status`, `get_files`, `process_selected`, `prepare_selected` (общий экземпляр через `get_controller`) |

## Поток работы

1. `start_search(папки, маска, background_mode)` — запуск поиска; повторный
   запуск во время работы возвращает `already_running`.
2. `get_status()` — прогресс поиска (с `files_per_sec`) и состояние задач.
3. `get_files()` — файлы из БД и найденные поиском с UI-статусами.
4. `process_selected(ids)` — «Сохранить»: фоновый разбор выбранных файлов.
5. `prepare_selected(ids)` — «Подготовить»: маппинг актуальных SAVED-файлов.
   `mapping_json` = {нормализованный заголовок: каноническое имя}; пустые
   заголовки пропускаются; если схемы нет — файл получает `NEEDS_MAPPING`.

## Word COM в потоках

Для `.doc` в `core/doc_converter.py` вызываются `pythoncom.CoInitialize` и
`CoUninitialize`. Без них конвертация в фоновом потоке молча возвращала
`None`, и файл получал `UNSUPPORTED`. Проверено на реальном `.doc`.

## Тесты

148 тестов в `tests/` (новые: `test_scanner.py`, `test_search_manager.py`,
`test_registrar.py`, `test_task_manager.py`, `test_controller.py`, в том числе
остановка долгого поиска).
