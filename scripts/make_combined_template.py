"""Собирает `PQ/Общая/шаблон ВОР+СО.xlsx` из `PQ/ВОР/шаблон ВОР.xlsx`.

Общая книга: запросы ВОР (как в шаблоне ВОР) + запросы СО (код из `PQ/СО/запросы/` под префиксом `СО_`)
+ запросы сверки из `PQ/Общая/запросы/`. Листы:
- `СписокВОР`, `СписокСО` (списки CSV, строки пишет приложение);
- `Справочники` (исходная таблица справочника колонок);
- `Пересечение`, `Только_в_СО`, `Только_в_ВОР`, `Связь_ВОР_СО` - таблицы сверки.
Остальные запросы (ФайлBinary, СО_ФайлBinary, Prefix и т.д.) листов не имеют.
Справочник колонок СО зашит в запрос `СО_СправочникКолонок` (роли и варианты - из make_so_template.py).

Запуск (нужны пакеты проекта, например из venv): `python -I -X utf8 scripts/make_combined_template.py`.
Книга-источник не меняется. Код запросов записывается через `scripts/pq_sync.py import --add`.
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
from make_so_template import SO_VARIANTS  # noqa: E402

SOURCE = os.path.join("PQ", "ВОР", "шаблон ВОР.xlsx")
TARGET = os.path.join("PQ", "Общая", "шаблон ВОР+СО.xlsx")
SO_QUERIES = os.path.join("PQ", "СО", "запросы")
OWN_QUERIES = os.path.join("PQ", "Общая", "запросы")
WORK = os.path.join("data", "_combined_pq")

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

VOR_COLUMNS = ["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "NПП", "NВЛСР",
               "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "ЛистыРД", "NППРДСО", "ФормулаРасРасОбъРабИРасМат",
               "Раздел", "Проверка"]
SO_COLUMNS = ["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "РазделНПП",
              "Комплект", "NПП", "НаименованиеИТехХар", "ТипМаркаОбозначение", "КодПродукции", "Поставщик", "ЕдИзм", "КолВо",
              "Масса1ЕдКг", "Примечание", "Проверка", "КлючСО"]
VOR_REF = ["ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
           "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППРДСО"]
SO_REF = ["ИмяФайла", "Таблица", "Строка", "Раздел", "Комплект", "NПП", "НаименованиеИТехХар", "ЕдИзм", "КолВо", "Примечание"]

# Новые таблицы запросов (лист и таблица называются как запрос): имя -> (столбцы, ширины)
QUERY_SHEETS: dict[str, tuple[list[str], list[int]]] = {
    "Пересечение": (["ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "NППСО", "СО_Наименование", "СтрокВОР", "СтрокСО", "КлючСО"],
                    [28, 14, 12, 12, 60, 10, 10, 60]),
    "Только_в_СО": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "Комплект",
                     "NПП", "НаименованиеИТехХар", "ЕдИзм", "КолВо", "Примечание", "КлючСО"],
                    [46, 28, 14, 12, 50, 9, 8, 50, 12, 10, 60, 10, 10, 30, 60]),
    "Только_в_ВОР": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
                      "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППСО", "Причина", "КлючСО"],
                     [46, 28, 14, 12, 50, 9, 8, 50, 10, 60, 10, 10, 20, 12, 24, 60]),
    "Связь_ВОР_СО": (["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
                      "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППСО", "КлючСО",
                      *("СО_" + c for c in SO_REF)],
                     [46, 28, 14, 12, 50, 9, 8, 50, 10, 60, 10, 10, 20, 12, 60,
                      50, 9, 8, 40, 12, 10, 60, 10, 10, 30]),
}
# Промежуточные запросы: на лист не загружаются (только соединение), чтобы не плодить листы
CONNECTION_ONLY = ["СО_ФайлBinary"]
# Листы шаблона ВОР, которые в общей книге не нужны (запросы остаются соединениями)
DROP_SHEETS = ["СправочникКолонок", "Prefix", "СписокФайлов", "ЗадатьДиректорию", "РабочаяДиректория", "ФайлBinary"]
LIST_SHEET = "СписокСО"
# Порядок листов в книге: имя -> после какого листа вставить
INSERT_AFTER = {LIST_SHEET: "СписокВОР"}


def _cell(ref: str, value: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _row(number: int, values: list[str]) -> str:
    cells = "".join(_cell(f"{qb._col_letter(i)}{number}", v) for i, v in enumerate(values))
    return f'<row r="{number}" spans="1:{len(values)}">{cells}</row>'


def _cols(widths: list[int]) -> str:
    return "<cols>" + "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1)) + "</cols>"


def _worksheet(sheetdata: str, dimension: str, cols: str, tab_selected: bool = False) -> str:
    selected = ' tabSelected="1"' if tab_selected else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{NS}" xmlns:r="{REL}"><dimension ref="{dimension}"/>'
            f'<sheetViews><sheetView{selected} workbookViewId="0">'
            '<selection activeCell="A1" sqref="A1"/></sheetView></sheetViews>'
            f'<sheetFormatPr defaultRowHeight="15"/>{cols}<sheetData>{sheetdata}</sheetData>'
            '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
            '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>')


def _query_table(table_id: int, name: str, columns: list[str]) -> str:
    n, last = len(columns), qb._col_letter(len(columns) - 1)
    cols = "".join(f'<tableColumn id="{i}" uniqueName="{i}" name="{escape(c)}" queryTableFieldId="{i}"/>'
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
            'applyNumberFormats="0" applyBorderFormats="0" applyFontFormats="1" applyPatternFormats="1" '
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
                 table_id: int, query_table_no: int, connection_id: int) -> None:
    """Лист `name` с таблицей запроса: шапка и пустая строка (данные запишет Excel при обновлении)."""
    last = qb._col_letter(len(columns) - 1)
    widths = widths + [14] * (len(columns) - len(widths))
    sheet = _worksheet(_row(1, columns) + f'<row r="2" spans="1:{len(columns)}"/>', f"A1:{last}2", _cols(widths))
    files[f"xl/worksheets/sheet{n}.xml"] = sheet.encode("utf-8")
    files[f"xl/worksheets/_rels/sheet{n}.xml.rels"] = _rels(f"../tables/table{table_id}.xml").encode("utf-8")
    files[f"xl/tables/table{table_id}.xml"] = _query_table(table_id, name, columns).encode("utf-8")
    files[f"xl/tables/_rels/table{table_id}.xml.rels"] = _rels(f"../queryTables/queryTable{query_table_no}.xml").encode("utf-8")
    files[f"xl/queryTables/queryTable{query_table_no}.xml"] = _query_table_part(connection_id, columns).encode("utf-8")


def build() -> None:
    with zipfile.ZipFile(SOURCE) as src:
        order = [i.filename for i in src.infolist()]
        files = {n: src.read(n) for n in order}
    text = lambda n: files[n].decode("utf-8")  # noqa: E731

    # --- существующие листы: чистим кэш, который остался от тестовых данных шаблона ---
    sheet1 = text("xl/worksheets/sheet1.xml")
    sheet1 = re.sub(r' topLeftCell="[^"]*"', "", sheet1)
    sheet1 = re.sub(r'<selection\b[^>]*/>', '<selection activeCell="A1" sqref="A1"/>', sheet1)
    files["xl/worksheets/sheet1.xml"] = sheet1.encode("utf-8")

    # --- листы промежуточных запросов убираем: запросы остаются, но только как соединения (без загрузки на лист) ---
    wb0 = text("xl/workbook.xml")
    rels0 = text("xl/_rels/workbook.xml.rels")
    removed_parts: list[str] = []
    for sheet_name in DROP_SHEETS:
        rid = re.search(rf'<sheet name="{re.escape(sheet_name)}"[^>]*r:id="(rId\d+)"', wb0).group(1)
        rel_tag = re.search(rf'<Relationship\b[^>]*Id="{rid}"[^>]*/>', rels0).group(0)
        sheet_file = "xl/" + re.search(r'Target="([^"]*)"', rel_tag).group(1)
        rels0 = rels0.replace(rel_tag, "")
        removed_parts.append(sheet_file)
        sheet_rels = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
        for table in re.findall(r'Target="\.\./tables/([^"]*)"', text(sheet_rels)):
            removed_parts += [f"xl/tables/{table}", f"xl/tables/_rels/{table}.rels"]
            for qt in re.findall(r'Target="\.\./queryTables/([^"]*)"', text(f"xl/tables/_rels/{table}.rels")):
                removed_parts.append(f"xl/queryTables/{qt}")
        removed_parts.append(sheet_rels)
        wb0 = re.sub(rf'<sheet name="{re.escape(sheet_name)}"[^>]*/>', "", wb0)
    types0 = text("[Content_Types].xml")
    for part in removed_parts:
        files.pop(part, None)
        types0 = re.sub(rf'<Override\b[^>]*PartName="/{re.escape(part)}"[^>]*/>', "", types0)
    files["[Content_Types].xml"] = types0.encode("utf-8")
    files["xl/_rels/workbook.xml.rels"] = rels0.encode("utf-8")
    # имена ExternalData_1 старых листов привязаны к их номеру: пересчитываем по именам листов до удаления
    old_sheet_names = re.findall(r'<sheet name="([^"]*)"', text("xl/workbook.xml"))
    old_defined_all = re.findall(r'<definedName name="ExternalData_1" localSheetId="(\d+)" hidden="1">([^<]*)</definedName>',
                                 text("xl/workbook.xml"))
    kept_defined = {old_sheet_names[int(i)]: ref for i, ref in old_defined_all if old_sheet_names[int(i)] not in DROP_SHEETS}
    files["xl/workbook.xml"] = wb0.encode("utf-8")

    # --- СписокСО: пустой список (шапка в строке 15, как у СписокВОР), таблица 10 ---
    list_headers = re.findall(r'<tableColumn id="\d+" name="([^"]*)"', text("xl/tables/table1.xml"))
    sheet_cols = re.search(r"<cols>.*?</cols>", sheet1, re.DOTALL).group(0)
    list_sheet = _worksheet(_row(15, list_headers) + '<row r="16" spans="1:18"/>', f"A15:{qb._col_letter(len(list_headers) - 1)}16",
                            sheet_cols)
    # строки шапки начинаются с 15-й: _row нумерует по параметру, поэтому всё готово
    files["xl/worksheets/sheet10.xml"] = list_sheet.encode("utf-8")
    files["xl/worksheets/_rels/sheet10.xml.rels"] = _rels("../tables/table10.xml").encode("utf-8")
    table2 = text("xl/tables/table1.xml").replace('id="2" name="СписокВОР" displayName="СписокВОР"',
                                                    'id="10" name="СписокСО" displayName="СписокСО"')
    files["xl/tables/table10.xml"] = table2.encode("utf-8")

    # --- новые листы с таблицами запросов ---
    sheet_no, table_id, qt_no, conn_id = 11, 11, 7, 22
    new_sheets: list[tuple[str, int]] = [(LIST_SHEET, 10)]
    connections = ""
    defined: dict[str, str] = {}
    for name, (columns, widths) in QUERY_SHEETS.items():
        _query_sheet(files, sheet_no, name, columns, widths, table_id, qt_no, conn_id)
        connections += _connection(conn_id, name)
        defined[name] = f"{name}!$A$1:${qb._col_letter(len(columns) - 1)}$2"
        new_sheets.append((name, sheet_no))
        sheet_no, table_id, qt_no, conn_id = sheet_no + 1, table_id + 1, qt_no + 1, conn_id + 1
    for name in CONNECTION_ONLY:
        connections += _connection(conn_id, name)
        conn_id += 1
    files["xl/connections.xml"] = text("xl/connections.xml").replace("</connections>", connections + "</connections>").encode("utf-8")

    # --- workbook.xml: листы, имена ExternalData_1 (localSheetId - номер листа по порядку) ---
    wb = text("xl/workbook.xml")
    old_sheets = re.findall(r'<sheet name="([^"]*)" sheetId="(\d+)" r:id="(rId\d+)"/>', wb)
    names = [s[0] for s in old_sheets]
    rel_ids = {}
    rels = text("xl/_rels/workbook.xml.rels")
    sheet_tags = {s[0]: f'<sheet name="{s[0]}" sheetId="{s[1]}" r:id="{s[2]}"/>' for s in old_sheets}
    for i, (name, number) in enumerate(new_sheets):
        rid = f"rId{100 + i}"
        rel_ids[name] = rid
        sheet_tags[name] = f'<sheet name="{name}" sheetId="{number}" r:id="{rid}"/>'
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="{rid}" Type="{REL}/worksheet" Target="worksheets/sheet{number}.xml"/></Relationships>')
        target = INSERT_AFTER.get(name)
        names.insert(names.index(target) + 1 if target in names else len(names), name)
    defined_by_sheet = dict(kept_defined)
    defined_by_sheet.update(defined)
    defined_xml = "".join(
        f'<definedName name="ExternalData_1" localSheetId="{names.index(name)}" hidden="1">{ref}</definedName>'
        for name, ref in sorted(defined_by_sheet.items(), key=lambda kv: names.index(kv[0])))
    wb = re.sub(r"<sheets>.*?</sheets>", lambda _m: "<sheets>" + "".join(sheet_tags[nm] for nm in names) + "</sheets>", wb, flags=re.DOTALL)
    wb = re.sub(r"<definedNames>.*?</definedNames>", lambda _m: f"<definedNames>{defined_xml}</definedNames>", wb, flags=re.DOTALL)
    files["xl/workbook.xml"] = wb.encode("utf-8")

    # --- связи пакета, типы содержимого, свойства; calcChain не нужен (формул больше нет) ---
    del files["xl/calcChain.xml"]
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
    """Код запросов СО под префиксом `СО_` и запросы сверки собираются в одну папку для импорта."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)

    def rename(code: str) -> str:
        for old in ("fnReadCsv", "СписокФайлов", "СправочникКолонок"):
            code = re.sub(rf'(?<![\w"]){old}(?![\w"])', "СО_" + old, code)
        return code

    def read(path: str) -> str:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()

    def write(name: str, code: str) -> None:
        with open(os.path.join(WORK, name + ".pq"), "w", encoding="utf-8") as f:
            f.write(code)

    for src, dst in (("fnReadCsv", "СО_fnReadCsv"), ("СписокФайлов", "СО_СписокФайлов"),
                     ("СО_База", "СО_База"), ("ФайлBinary", "СО_ФайлBinary")):
        write(dst, rename(read(os.path.join(SO_QUERIES, src + ".pq"))))

    # справочник колонок СО: те же роли и варианты, что в шаблоне СО (таблица книги ВОР - для ролей ВОР)
    rows = ",\n        ".join('{"%s", "%s"}' % (role, v.replace('"', '""')) for role, vs in SO_VARIANTS.items() for v in vs)
    write("СО_СправочникКолонок",
          'let\n    // Роли СО и написания шапок (источник - scripts/make_so_template.py, SO_VARIANTS)\n'
          '    Источник = #table({"Роль", "Вариант"}, {\n        ' + rows + '\n    })\nin\n    Источник\n')
    for name in os.listdir(OWN_QUERIES):
        shutil.copy(os.path.join(OWN_QUERIES, name), os.path.join(WORK, name))
    return WORK


def main() -> int:
    build()
    print("Книга собрана:", TARGET)
    queries = prepare_queries()
    cmd = [sys.executable, "-I", "-X", "utf8", os.path.join("scripts", "pq_sync.py"), "import", queries, TARGET, "--add"]
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

