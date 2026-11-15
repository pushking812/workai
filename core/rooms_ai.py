"""Распознавание экспликации помещений (PDF) моделью: ответ — сырой CSV.

Формат тот же, что у ручных `*.pdf.csv` в «ДопФайлы/Помещения»: 7 столбцов,
разделитель «,», все поля в кавычках, десятичная запятая. Если файл прочитать
нельзя, модель отвечает `ERROR: <причина>`.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Callable

from core import ai_client

HEADER = ["NN по правоустанавливающим документам", "NN внутр.", "Назначение помещений",
          "Площадь помещений по ПБ, кв.м", "Площадь помещений по факту, кв.м",
          "Подразделение использующ. помещение", "Примечание"]

SYSTEM = (
    "Ты переводишь таблицу из PDF (инвентаризационная ведомость помещений) в CSV. "
    "Отвечай ТОЛЬКО сырым CSV: без пояснений, без markdown и без обёртки ```. "
    "Первая строка — заголовок ровно из 7 столбцов: "
    + ",".join('"%s"' % h for h in HEADER) + ". "
    "Разделитель «,», все поля в двойных кавычках, десятичная запятая («3,0»). "
    "Одна строка таблицы — одна строка CSV. Заголовки разделов и этажей (например "
    "«ТРЕТИЙ ЭТАЖ *, Московский пр., д. 28») — строка, где заполнено только первое поле. "
    "Строки «Итого» и подписи не включай. Объединённые ячейки повторяй в каждой строке. "
    "Ничего не придумывай и не исправляй: нечитаемое поле оставь пустым. "
    "Если файл прочитать невозможно или это не такая таблица, ответь одной строкой "
    "`ERROR: <причина>`."
)
PROMPT = "Переведи таблицу из приложенного PDF в CSV по правилам."


def parse_csv_text(text: str) -> list[list[str]]:
    """Сырой CSV от модели -> строки (без заголовка), каждая дополнена до 7 полей."""
    t = ai_client.strip_fences(text)
    if t.upper().startswith("ERROR"):
        raise ai_client.AIError(t.split(":", 1)[-1].strip() or "модель не смогла прочитать файл", "model_refused")
    rows = [r for r in csv.reader(io.StringIO(t), delimiter=",", quotechar='"') if any(c.strip() for c in r)]
    if not rows:
        raise ai_client.AIError("пустой ответ модели", "empty")
    if len(rows[0]) < 5:
        raise ai_client.AIError("ответ не похож на CSV: " + t[:80], "bad_format")
    return [(r + [""] * 7)[:7] for r in rows[1:]]


def ocr_with_ai(pdf: str | Path, settings: dict[str, Any],
                ask: Callable[..., str] = ai_client.ask) -> list[list[str]]:
    """PDF -> строки таблицы через модель. Бросает AIError, если модель отказалась."""
    text = ask(PROMPT, settings=settings, system=SYSTEM, files=[ai_client.file_part(pdf)])
    return parse_csv_text(text)
