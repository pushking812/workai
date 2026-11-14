"""ДатаИзм в шаблонах: Excel протягивает формат первой строки и сохранённый тип столбца на все строки.

Если в шаблоне ВОР+СО у таблицы с ДатаИзм во 2-й строке нет ячейки со стилем даты, после обновления дата стоит только в
первой строке, остальные показывают число (46064). У ВОР и СО важен сохранённый тип столбца в метаданных запроса.
"""

from __future__ import annotations

import base64
import html
import os
import re
import struct
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
VOR_SO = os.path.join(ROOT, "PQ", "ВОР+СО", "шаблон ВОР+СО.xlsx")
NULLABLE_DATE = 7


def _column_letter(index: int) -> str:
    letters, index = "", index + 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _date_xf_ids(z: zipfile.ZipFile) -> set[int]:
    styles = ET.fromstring(z.read("xl/styles.xml"))
    custom = {int(n.get("numFmtId")): n.get("formatCode") for n in styles.findall(".//m:numFmts/m:numFmt", NS)}
    result = set()
    for i, xf in enumerate(styles.findall("m:cellXfs/m:xf", NS)):
        fmt_id = int(xf.get("numFmtId"))
        if 14 <= fmt_id <= 17 or "yy" in custom.get(fmt_id, ""):
            result.add(i)
    return result


def _fill_column_types(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        item = next(n for n in z.namelist() if re.fullmatch(r"customXml/item\d+\.xml", n)
                    and b"DataMashup" in z.read(n).replace(b"\x00", b""))
        raw = z.read(item)
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    data = base64.b64decode(re.search(r">([A-Za-z0-9+/=\s]+)</DataMashup>", text).group(1))
    off = 4
    off += 4 + struct.unpack("<I", data[off:off + 4])[0]
    off += 4 + struct.unpack("<I", data[off:off + 4])[0]
    length = struct.unpack("<I", data[off:off + 4])[0]
    xml = data[off + 4 + 8:off + 4 + length].decode("utf-8-sig")
    types = {}
    for item_xml in re.findall(r"<Item>(.*?)</Item>", xml, re.S):
        path_match = re.search(r"<ItemPath>(.*?)</ItemPath>", item_xml)
        value = re.search(r'<Entry Type="FillColumnTypes" Value="s([^"]*)"', item_xml)
        if path_match and value:
            name = urllib.parse.unquote(html.unescape(path_match.group(1)))
            if name.count("/") == 1:
                types[name.split("/")[1]] = base64.b64decode(value.group(1))
    return types


@pytest.mark.skipif(not os.path.isfile(VOR_SO), reason="нет шаблона ВОР+СО (xlsx в .gitignore)")
def test_vor_so_date_columns_have_date_cell_in_first_data_row():
    with zipfile.ZipFile(VOR_SO) as z:
        date_styles = _date_xf_ids(z)
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        checked = 0
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).findall(".//m:sheets/m:sheet", NS):
            target = rels[sheet.get("{%s}id" % NS["r"])].lstrip("/")
            sheet_path = target if target.startswith("xl/") else "xl/" + target
            rels_path = sheet_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
            if rels_path not in z.namelist():
                continue
            for rel in ET.fromstring(z.read(rels_path)):
                if not rel.get("Type").endswith("/table"):
                    continue
                table = ET.fromstring(z.read("xl/" + rel.get("Target").replace("../", "")))
                columns = [c.get("name") for c in table.findall(".//m:tableColumn", NS)]
                if "ДатаИзм" not in columns:
                    continue
                address = _column_letter(columns.index("ДатаИзм")) + "2"
                cell = re.search(rf'<c r="{address}"([^>]*?)/?>', z.read(sheet_path).decode("utf-8"))
                style = re.search(r's="(\d+)"', cell.group(1)) if cell else None
                assert style and int(style.group(1)) in date_styles, f"{sheet.get('name')}: {address} без стиля даты"
                checked += 1
        assert checked >= 4


@pytest.mark.parametrize("name", ["ВОР", "СО"])
def test_vor_and_so_stored_date_type(name):
    path = os.path.join(ROOT, "PQ", name, f"шаблон {name}.xlsx")
    if not os.path.isfile(path):
        pytest.skip("нет шаблона (xlsx в .gitignore)")
    code = open(os.path.join(ROOT, "PQ", name, "запросы", "ФайлBinary.pq"), encoding="utf-8").read()
    assert re.search(r'\{"ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм"', code)  # ДатаИзм - четвёртый столбец
    assert _fill_column_types(path)["ФайлBinary"][3] == NULLABLE_DATE
