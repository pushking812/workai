"""Точка входа.

Запуск:
    python main.py                  - окно приложения (Этап 4)
    python main.py ВОР              - консольный разбор папки (Этап 1)
    python main.py ВОР --db data/app.db

Консольная логика находится в `scripts/process_folder.py`.
"""

from __future__ import annotations

import os
import sys

WINDOW_TITLE = "БД Строительных Документов"
WINDOW_SIZE = (1200, 800)
# Меньше окно не делаем: в одной строке шапки должны помещаться все элементы.
MIN_SIZE = (1000, 500)
UI_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")


def run_gui() -> int:
    import webview

    from api.webview_api import Api

    webview.create_window(
        title=WINDOW_TITLE,
        url=UI_INDEX,
        js_api=Api(),
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        resizable=True,
        min_size=MIN_SIZE,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from scripts.process_folder import main

        raise SystemExit(main())
    raise SystemExit(run_gui())
