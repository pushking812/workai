"""Точка входа Этапа 1.

Запуск:
    python main.py ВОР
    python main.py ВОР --db data/app.db

Вся логика находится в `scripts/process_folder.py`; здесь только вызов.
"""

from __future__ import annotations

from scripts.process_folder import main

if __name__ == "__main__":
    raise SystemExit(main())
