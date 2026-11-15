"""Собирает `PQ/ВОР+СО/шаблон ВОР+СО.xlsx` (основа - пакет `PQ/ВОР/шаблон ВОР.xlsx`, его листы и запросы убираются).

Книга ВОР+СО не обрабатывает данные: она читает готовые таблицы `ФайлBinary` из книг ВОР и СО
(`Excel.Workbook(File.Contents(...))`), а пути берёт из таблицы `Параметры`. Листы:
- `Параметры` - таблица `Параметры` (Папка, ФайлВОР, ФайлСО). Папка - формула с путём этой книги,
  поэтому пути относительные: три файла в одной папке работают после копирования;
- `Пересечение`, `Только_в_СО`, `Только_в_ВОР`, `Связь_ВОР_СО` - таблицы сверки.
Запросы: `ПутьВОР`, `ПутьСО`, `ВОР_Строки`, `СО_Строки` (чтение книг) из `PQ/ВОР+СО/запросы/`; `ВОР_СвязьСО` и
`fnOnlyAllowedChars` берутся из `PQ/ВОР/запросы/` (источник заменяется на `ВОР_Строки`); запросы сверки - из `PQ/ВОР+СО/запросы/`.
Загрузку в модель данных и сводную таблицу пользователь добавляет в шаблоне вручную (в Excel).

Запуск (нужны пакеты проекта, например из venv): `python -I -X utf8 scripts/make_vor_so_template.py`.
Книга-источник не меняется. Код запросов записывается через `scripts/pq_sync.py import --add --prune`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core import query_builder as qb  # noqa: E402

SOURCE = os.path.join("PQ", "ВОР", "шаблон ВОР.xlsx")
TARGET = os.path.join("PQ", "ВОР+СО", "шаблон ВОР+СО.xlsx")
VOR_QUERIES = os.path.join("PQ", "ВОР", "запросы")
OWN_QUERIES = os.path.join("PQ", "ВОР+СО", "запросы")
WORK = os.path.join("data", "_vor_so_pq")

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

SO_REF = ["ИмяФайла", "Таблица", "Строка", "Раздел", "Комплект", "NПП", "НаименованиеИТехХар", "ЕдИзм", "КолВо", "Примечание"]

PARAMS_SHEET = "Параметры"
PARAMS_COLUMNS = ["Папка", "ФайлВОР", "ФайлСО"]
PARAMS_DEFAULTS = ["", "ВОР.xlsx", "СО.xlsx"]
# Папка: путь к каталогу этой книги (CELL("filename") пуст, пока книга не сохранена)
FOLDER_FORMULA = 'LEFT(CELL("filename",A1),FIND("[",CELL("filename",A1))-1)'
PARAMS_HINTS = [
    "Книга читает готовые таблицы ФайлBinary из книг ВОР и СО. Сначала обновите и сохраните книги ВОР и СО, потом обновляйте эту книгу.",
    "Папка - формула (путь этой книги, книга должна быть сохранена). Если книги ВОР и СО лежат в другой папке, впишите путь вместо формулы.",
    "Ошибка про уровни конфиденциальности (Formula.Firewall): Данные - Получить данные - Параметры запроса - Конфиденциальность - Игнорировать уровни.",
]

# Таблицы запросов (лист и таблица называются как запрос): имя -> (столбцы, ширины)
QUERY_SHEETS: dict[str, tuple[list[str], list[int]]] = {
    "Пересечение": (["ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "NППСО", "СО_Наименование", "СтрокВОР", "СтрокСО", "Связь", "КлючСО"],
                    [28, 14, 12, 12, 60, 10, 10, 34, 60]),
    "Только_в_СО": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "Комплект",
                     "NПП", "НаименованиеИТехХар", "ЕдИзм", "КолВо", "Примечание", "КлючСО"],
                    [46, 28, 14, 12, 50, 9, 8, 50, 12, 10, 60, 10, 10, 30, 60]),
    "Только_в_ВОР": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
                      "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППСО", "Причина", "КлючСО"],
                     [46, 28, 14, 12, 50, 9, 8, 50, 10, 60, 10, 10, 20, 12, 24, 60]),
    "Связь_ВОР_СО": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
                      "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППСО", "КлючСО",
                      *("СО_" + c for c in SO_REF),
                      "ВОР_СтрокГруппы", "СО_СтрокГруппы", "СО_УчтеноОдинРаз", "ВОР_УчтеноОдинРаз", "СтатусПары", "ОценкаПары", "ЭтоПара", "СО_Справочно", "Сравнимо"],
                     [46, 28, 14, 12, 50, 9, 8, 50, 10, 60, 10, 10, 20, 12, 60,
                      50, 9, 8, 40, 12, 10, 60, 10, 10, 30, 12, 12, 12, 16, 16, 10, 8]),
    "Ошибки": (["ТипПроблемы", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "NПП", "СтрокВОР", "СтрокСО",
                "НаименованиеВОР", "НаименованиеСО", "ОценкаПары", "Пояснение", "КлючСО"],
               [28, 28, 14, 12, 10, 10, 10, 60, 60, 10, 70, 60]),
}
# Запросы без листа (только соединение): читаемые таблицы ВОР и СО и связь ВОР -> СО
CONNECTION_ONLY = ["ВОР_Строки", "СО_Строки", "ВОР_СвязьСОСтрогая", "ВОР_СвязьСО", "СвязьПоИмени", "ВОР_СвязьИтог"]


def _cell(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _row(number: int, values: list[str]) -> str:
    cells = "".join(_cell(f"{qb._col_letter(i)}{number}", v) for i, v in enumerate(values))
    return f'<row r="{number}" spans="1:{len(values)}">{cells}</row>'


def _cols(widths: list[int], styles: dict[int, int] | None = None) -> str:
    """Ширины столбцов; `styles` - номер столбца (с 1) -> индекс стиля (формат даты для ДатаИзм)."""
    styles = styles or {}
    return "<cols>" + "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"' + (f' style="{styles[i]}"' if i in styles else "") + "/>"
        for i, w in enumerate(widths, 1)) + "</cols>"


def _worksheet(sheetdata: str, dimension: str, cols: str, tab_selected: bool = False) -> str:
    selected = ' tabSelected="1"' if tab_selected else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{NS}" xmlns:r="{REL}"><dimension ref="{dimension}"/>'
            f'<sheetViews><sheetView{selected} workbookViewId="0">'
            '<selection activeCell="A1" sqref="A1"/></sheetView></sheetViews>'
            f'<sheetFormatPr defaultRowHeight="15"/>{cols}<sheetData>{sheetdata}</sheetData>'
            '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
            '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>')


def _add_date_dxf(styles_xml: str) -> tuple[str, int]:
    """Добавляет в стили дифференциальный формат «дата» (для dataDxfId столбцов таблицы) и возвращает (xml, индекс)."""
    dxf = '<dxf><numFmt numFmtId="14" formatCode="dd/mm/yyyy"/></dxf>'
    m = re.search(r'<dxfs count="(\d+)"\s*/>', styles_xml)
    if m:
        return styles_xml[:m.start()] + f'<dxfs count="1">{dxf}</dxfs>' + styles_xml[m.end():], 0
    m = re.search(r'<dxfs count="(\d+)"\s*>(.*?)</dxfs>', styles_xml, re.S)
    if m:
        count = len(re.findall(r"<dxf>|<dxf\s", m.group(2)))
        return (styles_xml[:m.start()] + f'<dxfs count="{count + 1}">{m.group(2)}{dxf}</dxfs>'
                + styles_xml[m.end():]), count
    block = f'<dxfs count="1">{dxf}</dxfs>'
    m = re.search(r"<tableStyles\b|<colors\b|<extLst\b|</styleSheet>", styles_xml)
    return styles_xml[:m.start()] + block + styles_xml[m.start():], 0


def _query_table(table_id: int, name: str, columns: list[str], date_dxf: int) -> str:
    n, last = len(columns), qb._col_letter(len(columns) - 1)
    cols = "".join(f'<tableColumn id="{i}" uniqueName="{i}" name="{escape(c)}" queryTableFieldId="{i}"'
                   + (f' dataDxfId="{date_dxf}"' if c == "ДатаИзм" else "") + "/>"
                   for i, c in enumerate(columns, 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<table xmlns="{NS}" id="{table_id}" name="{name}" displayName="{name}" ref="A1:{last}2" '
            'tableType="queryTable" totalsRowShown="0">'
            f'<autoFilter ref="A1:{last}2"/><tableColumns count="{n}">{cols}</tableColumns>'
            '<tableStyleInfo name="TableStyleMedium7" showFirstColumn="0" showLastColumn="0" '
            'showRowStripes="1" showColumnStripes="0"/></table>')


def _query_table_part(connection_id: int, columns: list[str]) -> str:
    n = len(columns)
    fields = "".join(f'<queryTableField id="{i}" name="{escape(c)}" tableColumnId="{i}"/>' for i, c in enumerate(columns, 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<queryTable xmlns="{NS}" name="ExternalData_1" connectionId="{connection_id}" autoFormatId="0" '
            'applyNumberFormats="1" applyBorderFormats="0" applyFontFormats="1" applyPatternFormats="1" '
            'applyAlignmentFormats="0" applyWidthHeightFormats="0">'
            f'<queryTableRefresh preserveSortFilterLayout="0" nextId="{n + 1}"><queryTableFields count="{n}">{fields}'
            '</queryTableFields></queryTableRefresh></queryTable>')


def _connection(connection_id: int, name: str) -> str:
    return (f'<connection id="{connection_id}" keepAlive="1" name="Запрос — {name}" '
            f'description="Соединение с запросом &quot;{name}&quot; в книге." type="5" refreshedVersion="6" '
            f'background="1" saveData="1"><dbPr connection="Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;'
            f'Location={name}" command="SELECT * FROM [{name}]"/></connection>')


def _rels(target: str) -> str:
    kind = "queryTable" if "queryTable" in target else "table"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/{kind}" Target="{target}"/></Relationships>')


def _query_sheet(files: dict[str, bytes], n: int, name: str, columns: list[str], widths: list[int],
                 table_id: int, query_table_no: int, connection_id: int, date_style: int, date_dxf: int) -> None:
    """Лист `name` с таблицей запроса: шапка и пустая строка (данные запишет Excel при обновлении).

    Столбец ДатаИзм (тип date в запросе) получает формат даты, иначе Excel показывает число.
    """
    last = qb._col_letter(len(columns) - 1)
    widths = widths + [14] * (len(columns) - len(widths))
    date_cols = {i: date_style for i, c in enumerate(columns, 1) if c == "ДатаИзм"}
    # Excel переносит формат первой строки данных на все строки результата, поэтому стиль задаём и в ячейке второй строки
    row2 = "".join(f'<c r="{qb._col_letter(i - 1)}2" s="{s}"/>' for i, s in date_cols.items())
    sheet = _worksheet(_row(1, columns) + f'<row r="2" spans="1:{len(columns)}">{row2}</row>', f"A1:{last}2",
                       _cols(widths, date_cols))
    files[f"xl/worksheets/sheet{n}.xml"] = sheet.encode("utf-8")
    files[f"xl/worksheets/_rels/sheet{n}.xml.rels"] = _rels(f"../tables/table{table_id}.xml").encode("utf-8")
    files[f"xl/tables/table{table_id}.xml"] = _query_table(table_id, name, columns, date_dxf).encode("utf-8")
    files[f"xl/tables/_rels/table{table_id}.xml.rels"] = _rels(f"../queryTables/queryTable{query_table_no}.xml").encode("utf-8")
    files[f"xl/queryTables/queryTable{query_table_no}.xml"] = _query_table_part(connection_id, columns).encode("utf-8")


def _params_sheet(files: dict[str, bytes], n: int, table_id: int) -> None:
    """Лист «Параметры»: таблица `Параметры` (A1:C2), в A2 формула папки; ниже подсказки."""
    cells = (f'<c r="A2" t="str"><f>{escape(FOLDER_FORMULA)}</f><v></v></c>'
             + "".join(_cell(f"{qb._col_letter(i)}2", v) for i, v in enumerate(PARAMS_DEFAULTS) if i > 0))
    rows = _row(1, PARAMS_COLUMNS) + f'<row r="2" spans="1:3">{cells}</row>'
    for i, hint in enumerate(PARAMS_HINTS):
        rows += _row(4 + i, [hint])
    sheet = _worksheet(rows, "A1:C6", _cols([60, 18, 18]), tab_selected=True)
    files[f"xl/worksheets/sheet{n}.xml"] = sheet.encode("utf-8")
    files[f"xl/worksheets/_rels/sheet{n}.xml.rels"] = _rels(f"../tables/table{table_id}.xml").encode("utf-8")
    columns = "".join(f'<tableColumn id="{i}" name="{c}"/>' for i, c in enumerate(PARAMS_COLUMNS, 1))
    files[f"xl/tables/table{table_id}.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="{NS}" id="{table_id}" name="{PARAMS_SHEET}" displayName="{PARAMS_SHEET}" ref="A1:C2" totalsRowShown="0">'
        f'<autoFilter ref="A1:C2"/><tableColumns count="3">{columns}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/></table>').encode("utf-8")


def build() -> None:
    with zipfile.ZipFile(SOURCE) as src:
        order = [i.filename for i in src.infolist()]
        files = {n: src.read(n) for n in order}
    text = lambda n: files[n].decode("utf-8")  # noqa: E731

    # --- все листы шаблона ВОР убираем вместе с таблицами, запросами таблиц и соединениями ---
    wb0 = text("xl/workbook.xml")
    rels0 = text("xl/_rels/workbook.xml.rels")
    removed_parts: list[str] = []
    for sheet_name in re.findall(r'<sheet name="([^"]*)"', wb0):
        rid = re.search(rf'<sheet name="{re.escape(sheet_name)}"[^>]*r:id="(rId\d+)"', wb0).group(1)
        rel_tag = re.search(rf'<Relationship\b[^>]*Id="{rid}"[^>]*/>', rels0).group(0)
        sheet_file = "xl/" + re.search(r'Target="([^"]*)"', rel_tag).group(1)
        rels0 = rels0.replace(rel_tag, "")
        removed_parts.append(sheet_file)
        sheet_rels = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
        for table in re.findall(r'Target="\.\./tables/([^"]*)"', text(sheet_rels)):
            removed_parts.append(f"xl/tables/{table}")
            table_rels = f"xl/tables/_rels/{table}.rels"
            if table_rels in files:
                removed_parts.append(table_rels)
                for qt in re.findall(r'Target="\.\./queryTables/([^"]*)"', text(table_rels)):
                    removed_parts.append(f"xl/queryTables/{qt}")
        removed_parts.append(sheet_rels)
    wb0 = re.sub(r"<sheets>.*?</sheets>", "<sheets></sheets>", wb0, flags=re.DOTALL)
    wb0 = re.sub(r"<definedNames>.*?</definedNames>", "<definedNames></definedNames>", wb0, flags=re.DOTALL)
    types0 = text("[Content_Types].xml")
    for part in removed_parts:
        files.pop(part, None)
        types0 = re.sub(rf'<Override\b[^>]*PartName="/{re.escape(part)}"[^>]*/>', "", types0)
    files["[Content_Types].xml"] = types0.encode("utf-8")
    files["xl/_rels/workbook.xml.rels"] = rels0.encode("utf-8")
    # тестовые строки шаблона ВОР в книге не нужны, все новые листы пишут текст в ячейках
    files["xl/sharedStrings.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                     f'<sst xmlns="{NS}" count="0" uniqueCount="0"/>').encode("utf-8")
    files["xl/connections.xml"] = re.sub(r"(<connections\b[^>]*>).*(</connections>)", r"\1\2", text("xl/connections.xml"),
                                         flags=re.DOTALL).encode("utf-8")
    files["xl/workbook.xml"] = wb0.encode("utf-8")

    # --- Параметры (лист 10, таблица 10) и листы с таблицами запросов ---
    styles_xml, date_style = qb._add_date_style(text("xl/styles.xml"))
    styles_xml, date_dxf = _add_date_dxf(styles_xml)
    files["xl/styles.xml"] = styles_xml.encode("utf-8")
    _params_sheet(files, 10, 10)
    sheet_no, table_id, qt_no, conn_id = 11, 11, 7, 22
    new_sheets: list[tuple[str, int]] = [(PARAMS_SHEET, 10)]
    connections = ""
    defined: dict[str, str] = {}
    for name, (columns, widths) in QUERY_SHEETS.items():
        _query_sheet(files, sheet_no, name, columns, widths, table_id, qt_no, conn_id, date_style, date_dxf)
        connections += _connection(conn_id, name)
        defined[name] = f"{name}!$A$1:${qb._col_letter(len(columns) - 1)}$2"
        new_sheets.append((name, sheet_no))
        sheet_no, table_id, qt_no, conn_id = sheet_no + 1, table_id + 1, qt_no + 1, conn_id + 1
    for name in CONNECTION_ONLY:
        connections += _connection(conn_id, name)
        conn_id += 1
    files["xl/connections.xml"] = text("xl/connections.xml").replace("</connections>", connections + "</connections>").encode("utf-8")

    # --- workbook.xml: листы, имена ExternalData_1 (localSheetId - номер листа по порядку), пересчёт формулы папки ---
    wb = text("xl/workbook.xml")
    names: list[str] = []
    sheet_tags: list[str] = []
    rels = text("xl/_rels/workbook.xml.rels")
    for i, (name, number) in enumerate(new_sheets):
        rid = f"rId{100 + i}"
        names.append(name)
        sheet_tags.append(f'<sheet name="{name}" sheetId="{number}" r:id="{rid}"/>')
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" Type="{REL}/worksheet" Target="worksheets/sheet{number}.xml"/></Relationships>')
    defined_xml = "".join(
        f'<definedName name="ExternalData_1" localSheetId="{names.index(name)}" hidden="1">{ref}</definedName>'
        for name, ref in defined.items())
    wb = wb.replace("<sheets></sheets>", "<sheets>" + "".join(sheet_tags) + "</sheets>")
    wb = wb.replace("<definedNames></definedNames>", f"<definedNames>{defined_xml}</definedNames>")
    # активный лист и первый видимый - из шаблона ВОР (там 8 листов): номера вне диапазона Excel не открывает
    wb = re.sub(r'\s(firstSheet|activeTab)="\d+"', "", wb)
    wb = re.sub(r"<calcPr\b[^>]*/>", '<calcPr calcId="162913" fullCalcOnLoad="1"/>', wb)
    files["xl/workbook.xml"] = wb.encode("utf-8")

    # --- связи пакета, типы содержимого, свойства; calcChain не нужен ---
    files.pop("xl/calcChain.xml", None)
    rels = re.sub(r'<Relationship\b[^>]*calcChain[^>]*/>', "", rels)
    files["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")
    types = re.sub(r'<Override\b[^>]*calcChain[^>]*/>', "", text("[Content_Types].xml"))
    overrides = ""
    for _name, number in new_sheets:
        overrides += (f'<Override PartName="/xl/worksheets/sheet{number}.xml" ContentType="application/vnd.openxmlformats-'
                      'officedocument.spreadsheetml.worksheet+xml"/>')
    for t in range(10, table_id):
        overrides += (f'<Override PartName="/xl/tables/table{t}.xml" ContentType="application/vnd.openxmlformats-'
                      'officedocument.spreadsheetml.table+xml"/>')
    for q in range(7, qt_no):
        overrides += (f'<Override PartName="/xl/queryTables/queryTable{q}.xml" ContentType="application/vnd.openxmlformats-'
                      'officedocument.spreadsheetml.queryTable+xml"/>')
    files["[Content_Types].xml"] = types.replace("</Types>", overrides + "</Types>").encode("utf-8")
    app = text("docProps/app.xml")
    app = re.sub(r"<vt:i4>\d+</vt:i4>", f"<vt:i4>{len(names)}</vt:i4>", app, count=1)
    app = re.sub(r"<TitlesOfParts>.*?</TitlesOfParts>",
                 lambda _m: f'<TitlesOfParts><vt:vector size="{len(names)}" baseType="lpstr">'
                            + "".join(f"<vt:lpstr>{nm}</vt:lpstr>" for nm in names) + "</vt:vector></TitlesOfParts>",
                 app, flags=re.DOTALL)
    files["docProps/app.xml"] = app.encode("utf-8")

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    out_order = order + [n for n in files if n not in order]
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in out_order:
            if name in files:
                dst.writestr(name, files[name])


def prepare_queries() -> str:
    """Запросы книги ВОР+СО собираются в одну папку для импорта.

    `ВОР_СвязьСО` и `fnOnlyAllowedChars` - код шаблона ВОР без копии: у связи источник `ФайлBinary` заменяется
    на `ВОР_Строки` (таблица ВОР, прочитанная из книги). Остальное - из `PQ/ВОР+СО/запросы/`.
    """
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)

    def read(path: str) -> str:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()

    def write(name: str, code: str) -> None:
        with open(os.path.join(WORK, name + ".pq"), "w", encoding="utf-8") as f:
            f.write(code)

    link = read(os.path.join(VOR_QUERIES, "ВОР_СвязьСО.pq"))
    link, replaced = re.subn(r'(?<![\w"])ФайлBinary(?![\w"])', "ВОР_Строки", link)
    if not replaced:
        raise SystemExit("В ВОР_СвязьСО нет ссылки на ФайлBinary: источник не заменён")
    write("ВОР_СвязьСОСтрогая", link)  # ВОР_СвязьСО (второй проход без даты) - в OWN_QUERIES
    write("fnOnlyAllowedChars", read(os.path.join(VOR_QUERIES, "fnOnlyAllowedChars.pq")))
    for name in os.listdir(OWN_QUERIES):
        if name.endswith(".pq"):
            shutil.copy(os.path.join(OWN_QUERIES, name), os.path.join(WORK, name))
    return WORK


def main() -> int:
    global TARGET
    if len(sys.argv) > 1:  # другой файл результата: шаблон со сводной таблицей остаётся нетронутым
        TARGET = sys.argv[1]
    build()
    print("Книга собрана:", TARGET)
    queries = prepare_queries()
    cmd = [sys.executable, "-I", "-X", "utf8", os.path.join("scripts", "pq_sync.py"), "import", queries, TARGET,
           "--add", "--prune"]
    code = subprocess.call(cmd)
    shutil.rmtree(WORK, ignore_errors=True)
    if code == 0 and "--pivot" in sys.argv:
        # Сводная таблица создаётся в настоящем Excel (COM): сам запускает и закрывает свой Excel.
        tmp = TARGET + ".pivot.xlsx"
        code = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                os.path.join("scripts", "add_pivot.ps1"), "-Workbook", TARGET, "-Out", tmp])
        if code == 0:
            os.replace(tmp, TARGET)
    folder = os.path.dirname(TARGET)
    for leftover in (os.path.join(folder, "шаблон ВОР+СО.bak.xlsx"), os.path.join(folder, "_import_report.xlsx")):
        if os.path.exists(leftover):
            os.remove(leftover)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
