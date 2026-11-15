"""Справочник зданий, этажей и помещений (spravochniki.xlsx).

Читается как входной файл проекта, сам файл не правится. Листы: Здания,
Этажи, Помещения, Способы_прокладки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

DEFAULT_PATH = Path("spravochniki.xlsx")


@dataclass
class Reference:
    buildings: dict = field(default_factory=dict)   # код -> {"name", "full"}
    floors: dict = field(default_factory=dict)      # (здание, этаж) -> {"name", "ground_raw"}

    def building_name(self, code: str) -> str:
        b = self.buildings.get(code)
        return (b or {}).get("full") or (b or {}).get("name") or ""


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def load_reference(path: str | Path = DEFAULT_PATH) -> Reference:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ref = Reference()
    if "Здания" in wb.sheetnames:
        for r in list(wb["Здания"].iter_rows(values_only=True))[1:]:
            code = _s(r[0])
            if code:
                ref.buildings[code] = {"name": _s(r[1]), "full": _s(r[2]) if len(r) > 2 else ""}
    if "Этажи" in wb.sheetnames:
        for r in list(wb["Этажи"].iter_rows(values_only=True))[1:]:
            b, f = _s(r[0]), _s(r[1])
            if b and f:
                ref.floors[(b, f)] = {"name": _s(r[2]), "ground_raw": _s(r[3]) if len(r) > 3 else ""}
    wb.close()
    return ref


def ground_state(ref: Reference, building: str, floor: str) -> str:
    """'наземный' / 'подземный' / '' (неизвестно).

    Правила пользователя: ЗДЦ этаж ЭП (Этаж -1) считаем подземным,
    ДС1 целиком наземный; для остальных берём значение справочника,
    а при «по факту …» — слово из скобок.
    """
    if building == "ЗДЦ" and floor == "ЭП":
        return "подземный"
    if building == "ДС1":
        return "наземный"
    raw = (ref.floors.get((building, floor)) or {}).get("ground_raw", "").lower()
    m = re.search(r"по факту\s+(?:всё\s+|все\s+)?(наземный|подземный)", raw)
    if m:
        return m.group(1)
    for word in ("подземный", "наземный"):
        if raw.startswith(word):
            return word
    return ""
