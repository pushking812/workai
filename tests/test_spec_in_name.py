"""Позиции спецификации в наименовании работ ВОР («см. спец. Поз. 73», «(...СО (поз. 11.4-11.6))»).

Они добавляются к NППРДСО (запрос fnSpecFromName в шаблоне ВОР). Проверяем сам поиск в наименованиях
(scripts/find_spec_in_name.py), подключение функции в ФайлBinary и наличие её в шаблоне ВОР.
"""

from __future__ import annotations

import base64
import io
import os
import re
import struct
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from find_spec_in_name import POS_RE  # noqa: E402

VOR_TEMPLATE = os.path.join(ROOT, "PQ", "ВОР", "шаблон ВОР.xlsx")


@pytest.mark.parametrize("name, expected", [
    ("Монтаж гильз ... Пена огнестойкая \"Огнеза\" 2 шт. см. спец. Поз. 73", ["73"]),
    ("Монтаж TMC 22x10 Мини-канал с аксессуарами, см. спец. Поз. 75-76", ["75-76"]),
    ("Прокладка. Труба (ЕСТ-ПМ-80825-Р-1-СОУЭ.СО (поз. 12.14, 12.15)) Наземная часть.", ["12.14, 12.15"]),
    ("Монтаж Люк ... с аксессуарами см. Спец. Поз.58-64", ["58-64"]),
])
def test_positions_found_in_name(name, expected):
    found = [x.strip().rstrip(".,)") for x in POS_RE.findall(name)]
    assert found == expected


@pytest.mark.parametrize("name", [
    "Монтаж кабель-канала без ссылок на спецификацию",
    "Позиционирование оборудования 5 шт.",
])
def test_no_positions_in_plain_name(name):
    assert not [x for x in POS_RE.findall(name) if re.match(r"\d", x.strip())]


def test_file_binary_uses_function():
    code = open(os.path.join(ROOT, "PQ", "ВОР", "запросы", "ФайлBinary.pq"), encoding="utf-8").read()
    assert "fnSpecFromName([НаименованиеРабот])" in code
    assert os.path.isfile(os.path.join(ROOT, "PQ", "ВОР", "запросы", "fnSpecFromName.pq"))


def _section_m(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        item = next(n for n in z.namelist() if re.fullmatch(r"customXml/item\d+\.xml", n)
                    and b"DataMashup" in z.read(n).replace(b"\x00", b""))
        raw = z.read(item)
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    data = base64.b64decode(re.search(r">([A-Za-z0-9+/=\s]+)</DataMashup>", text).group(1))
    length = struct.unpack("<I", data[4:8])[0]
    with zipfile.ZipFile(io.BytesIO(data[8:8 + length])) as package:
        return package.read("Formulas/Section1.m").decode("utf-8-sig")


@pytest.mark.skipif(not os.path.isfile(VOR_TEMPLATE), reason="нет шаблона ВОР")
def test_vor_template_has_function():
    section = _section_m(VOR_TEMPLATE)
    assert "shared fnSpecFromName" in section
    assert "fnSpecFromName(" in section
