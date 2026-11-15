"""Настройки приложения: хранятся в `data/config.json` между сессиями."""

from __future__ import annotations

import json
import os
from typing import Any

from core.doc_types import KNOWN_DOC_TYPES

CONFIG_PATH = os.path.join("data", "config.json")

DEFAULTS: dict[str, Any] = {
    "directories": [],
    "root": "",
    "kits": [],
    "known_types": list(KNOWN_DOC_TYPES),
    "hide_unknown": False,
    "type_aliases": {},
    "search_by_type": False,
    "folder_filters": ["Изм", "Ред. формат"],
    "background_mode": True,
    "interval_minutes": 60,
    "ui": {},
    # AI-модель (docs/Ask API docs.txt): по умолчанию выключено; ключ можно не хранить,
    # а задать переменной окружения ASK_API_KEY (она главнее).
    "use_ai": False,
    "ai_api_key": "",
    "ai_model": "",
}


def public_view(settings: dict[str, Any]) -> dict[str, Any]:
    """Настройки для окна: ключ AI наружу не отдаётся, только признак «ключ есть»."""
    data = dict(settings)
    data["ai_key_set"] = bool(os.environ.get("ASK_API_KEY") or data.get("ai_api_key"))
    data["ai_key_from_env"] = bool(os.environ.get("ASK_API_KEY"))
    data.pop("ai_api_key", None)
    return data


def _str_list(raw: Any) -> list[str]:
    """Список непустых уникальных строк (порядок сохраняется)."""
    result: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip() and item.strip() not in result:
                result.append(item.strip())
    return result


def _normalize_aliases(raw: Any, types: list[str]) -> dict[str, list[str]]:
    """Алиасы по известным типам: {тип: [алиас, ...]}; чужие типы отбрасываются."""
    result: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for name in types:
            aliases = [a for a in _str_list(raw.get(name)) if a.lower() != name.lower()]
            if aliases:
                result[name] = aliases
    return result


def search_words(settings: dict[str, Any]) -> list[str]:
    """Слова для отбора файлов по имени: типы и их алиасы (если включён поиск по типу).

    Пустой список означает «не фильтровать».
    """
    if not settings.get("search_by_type"):
        return []
    aliases = settings.get("type_aliases") or {}
    words: list[str] = []
    for name in settings.get("known_types") or []:
        for word in [name, *aliases.get(name, [])]:
            if word and word.lower() not in (w.lower() for w in words):
                words.append(word)
    return words


def _normalize_ui(raw: Any) -> dict[str, Any]:
    """Состояние основного окна: дерево, сортировка, фильтр, раскрытые группы."""
    ui: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return ui
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
    data["known_types"] = list(KNOWN_DOC_TYPES)
    data["folder_filters"] = list(DEFAULTS["folder_filters"])
    if not isinstance(raw, dict):
        return data
    dirs = raw.get("directories")
    if isinstance(dirs, list):
        seen: list[str] = []
        for item in dirs:
            if isinstance(item, str) and item and item not in seen:
                seen.append(item)
        data["directories"] = seen
    if isinstance(raw.get("root"), str):
        data["root"] = raw["root"].strip()
    data["kits"] = _str_list(raw.get("kits"))
    if isinstance(raw.get("known_types"), list):
        data["known_types"] = _str_list(raw["known_types"])
    if isinstance(raw.get("hide_unknown"), bool):
        data["hide_unknown"] = raw["hide_unknown"]
    data["type_aliases"] = _normalize_aliases(raw.get("type_aliases"), data["known_types"])
    if isinstance(raw.get("search_by_type"), bool):
        data["search_by_type"] = raw["search_by_type"]
    if isinstance(raw.get("folder_filters"), list):
        data["folder_filters"] = _str_list(raw["folder_filters"])
    if isinstance(raw.get("background_mode"), bool):
        data["background_mode"] = raw["background_mode"]
    try:
        minutes = int(raw.get("interval_minutes", DEFAULTS["interval_minutes"]))
    except (TypeError, ValueError):
        minutes = DEFAULTS["interval_minutes"]
    data["interval_minutes"] = max(1, min(minutes, 24 * 60))
    data["ui"] = _normalize_ui(raw.get("ui"))
    if isinstance(raw.get("use_ai"), bool):
        data["use_ai"] = raw["use_ai"]
    if isinstance(raw.get("ai_api_key"), str):
        data["ai_api_key"] = raw["ai_api_key"].strip()
    if isinstance(raw.get("ai_model"), str):
        data["ai_model"] = raw["ai_model"].strip()
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
