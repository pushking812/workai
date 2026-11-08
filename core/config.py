"""Настройки приложения: хранятся в `data/config.json` между сессиями."""

from __future__ import annotations

import json
import os
from typing import Any

CONFIG_PATH = os.path.join("data", "config.json")

DEFAULTS: dict[str, Any] = {
    "directories": [],
    "background_mode": True,
    "interval_minutes": 60,
    "ui": {},
}

TREE_MODES = ("type-section", "section-type")


def _normalize_ui(raw: Any) -> dict[str, Any]:
    """Состояние основного окна: дерево, сортировка, фильтр, раскрытые группы."""
    ui: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return ui
    if raw.get("tree_mode") in TREE_MODES:
        ui["tree_mode"] = raw["tree_mode"]
    sort = raw.get("sort")
    if isinstance(sort, dict) and isinstance(sort.get("key"), str) and sort.get("dir") in (1, -1):
        ui["sort"] = {"key": sort["key"], "dir": sort["dir"]}
    if isinstance(raw.get("filter"), str):
        ui["filter"] = raw["filter"]
    if isinstance(raw.get("expanded"), list):
        ui["expanded"] = [k for k in raw["expanded"] if isinstance(k, str)]
    return ui


def _normalize(raw: Any) -> dict[str, Any]:
    data = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return data
    dirs = raw.get("directories")
    if isinstance(dirs, list):
        seen: list[str] = []
        for item in dirs:
            if isinstance(item, str) and item and item not in seen:
                seen.append(item)
        data["directories"] = seen
    if isinstance(raw.get("background_mode"), bool):
        data["background_mode"] = raw["background_mode"]
    try:
        minutes = int(raw.get("interval_minutes", DEFAULTS["interval_minutes"]))
    except (TypeError, ValueError):
        minutes = DEFAULTS["interval_minutes"]
    data["interval_minutes"] = max(1, min(minutes, 24 * 60))
    data["ui"] = _normalize_ui(raw.get("ui"))
    return data


def load_config(path: str | None = None) -> dict[str, Any]:
    """Читает конфиг; при отсутствии или порче файла возвращает значения по умолчанию."""
    try:
        with open(path or CONFIG_PATH, encoding="utf-8") as handle:
            return _normalize(json.load(handle))
    except (OSError, ValueError):
        return _normalize(None)


def save_config(settings: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """Сохраняет настройки (только известные ключи) и возвращает записанное."""
    target = path or CONFIG_PATH
    # Частичное обновление: ключи, которых нет в `settings`, сохраняют прежнее значение.
    merged = load_config(target)
    if isinstance(settings, dict):
        merged.update({k: v for k, v in settings.items() if k in DEFAULTS})
    data = _normalize(merged)
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return data
