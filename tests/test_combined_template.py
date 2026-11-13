"""Общая книга ВОР+СО: структура пакета после `make_combined_template.build()` (без импорта запросов)."""

from __future__ import annotations

import importlib
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "PQ", "ВОР", "шаблон ВОР.xlsx")

pytestmark = pytest.mark.skipif(not os.path.isfile(SOURCE), reason="нет шаблона ВОР (xlsx в .gitignore)")


@pytest.fixture()
def book(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(ROOT, "scripts"))
    monkeypatch.chdir(ROOT)
    module = importlib.import_module("make_combined_template")
    target = str(tmp_path / "общая.xlsx")
    monkeypatch.setattr(module, "TARGET", target)
    module.build()
    with zipfile.ZipFile(target) as z:
        yield module, z


def test_all_parts_are_well_formed(book):
    _module, z = book
    for name in z.namelist():
        if name.endswith((".xml", ".rels")):
            ET.fromstring(z.read(name))


def test_sheets_and_tables(book):
    module, z = book
    wb = z.read("xl/workbook.xml").decode("utf-8")
    names = re.findall(r'<sheet name="([^"]+)"', wb)
    assert names[:2] == ["СписокВОР", "СписокСО"]
    for expected in ["ФайлBinary", "СО_ФайлBinary", "Пересечение", "Только_в_СО", "Только_в_ВОР", "Связь_ВОР_СО"]:
        assert expected in names
    assert len(names) == len(set(names))
    tables = {}
    for name in z.namelist():
        if re.match(r"xl/tables/table\d+\.xml$", name):
            head = z.read(name).decode("utf-8")
            tables[re.search(r' name="([^"]+)"', head).group(1)] = head
    assert {"СписокВОР", "СписокСО", "Параметры", *module.QUERY_SHEETS} <= set(tables)
    # списки: 18 столбцов, шапка в строке 15
    for list_name in ("СписокВОР", "СписокСО"):
        assert 'ref="A15:R16"' in tables[list_name]
    ids = re.findall(r'<table\b[^>]*? id="(\d+)"', "".join(tables.values()))
    assert len(ids) == len(set(ids))


def test_connections_and_defined_names(book):
    module, z = book
    connections = z.read("xl/connections.xml").decode("utf-8")
    connection_ids = re.findall(r'<connection id="(\d+)"', connections)
    assert len(connection_ids) == len(set(connection_ids))
    for name in module.QUERY_SHEETS:
        assert f"Location={name}" in connections
    wb = z.read("xl/workbook.xml").decode("utf-8")
    sheets = re.findall(r'<sheet name="([^"]+)"', wb)
    local_ids = [int(i) for i in re.findall(r'<definedName name="ExternalData_1" localSheetId="(\d+)"', wb)]
    assert len(local_ids) == len(set(local_ids))
    assert all(0 <= i < len(sheets) for i in local_ids)
    for qt in (n for n in z.namelist() if n.startswith("xl/queryTables/")):
        assert re.search(r'connectionId="(\d+)"', z.read(qt).decode("utf-8")).group(1) in connection_ids
    content_types = z.read("[Content_Types].xml").decode("utf-8")
    for name in z.namelist():
        if re.match(r"xl/(worksheets/sheet|tables/table|queryTables/queryTable)\d+\.xml$", name):
            assert "/" + name in content_types


def test_query_columns_match_result_queries(book):
    """Столбцы заготовок таблиц совпадают с `Колонки` в M-коде запросов сверки."""
    module, _z = book
    code = open(os.path.join(ROOT, "PQ", "Общая", "запросы", "Только_в_ВОР.pq"), encoding="utf-8").read()
    columns = re.search(r"Колонки = \{(.*?)\},", code, re.DOTALL).group(1)
    assert re.findall(r'"([^"]+)"', columns) == module.QUERY_SHEETS["Только_в_ВОР"][0]
