"""Собирает `PQ/СО/шаблон СО.xlsx` из `PQ/ВОР/шаблон ВОР.xlsx`.

Шаблон СО — копия шаблона ВОР, в которой:
- лист и таблица списка файлов называются `СписокСО` (пустая заготовка, строки пишет приложение);
- справочник колонок содержит роли СО (см. SO_ROLES) с известными написаниями шапок;
- итоговая таблица `ФайлBinary` перестроена под колонки СО;
- запросы заменены кодом из `PQ/СО/запросы/` (запросы ВОР со ссылками на чертежи, листами и
  номерами пунктов СО не нужны: значения столбцов не преобразуются).

Запуск: `python -I -X utf8 scripts/make_so_template.py`. Книга-источник не меняется.
Код запросов затем записывается через `scripts/pq_sync.py import --add --prune`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape, unescape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import query_builder as qb  # noqa: E402

SOURCE = os.path.join("PQ", "ВОР", "шаблон ВОР.xlsx")
TARGET = os.path.join("PQ", "СО", "шаблон СО.xlsx")
QUERIES = os.path.join("PQ", "СО", "запросы")

# Роли СО и написания шапок, известные на сегодня (в шапках CSV они встречаются как есть).
SO_VARIANTS: dict[str, list[str]] = {
    "NПП": ["№ п/п", "Поз."],
    "НаименованиеИТехХар": ["Наименование и техническая характеристика"],
    "ТипМаркаОбозначение": ["Тип, марка, обозначение документа, опросного листа"],
    "КодПродукции": ["Код продукции", "Код оборудования, изделия, материала"],
    "Поставщик": ["Поставщик", "Завод-изготовитель"],
    "ЕдИзм": ["Единица измерения", "Ед. изме- ре- ния", "Ед. Изм."],
    "КолВо": ["Кол-во", "Коли- чест- во"],
    "Масса1ЕдКг": ["Масса 1 ед., кг", "Масса единицы, кг"],
    "Примечание": ["Примечание", "Приме- чание", "Прим."],
}
SO_ROLES = list(SO_VARIANTS)

# Столбцы итоговой таблицы `ФайлBinary` (запрос задаёт тот же порядок).
OUTPUT_COLUMNS = ["ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица",
                  "Строка", "Раздел", "РазделНПП", "Комплект", *SO_ROLES, "Проверка", "КлючСО"]

# Листы, где строки лежат в sharedStrings: переводим их в inlineStr, а sst очищаем.
SHEETS_WITH_STRINGS = [f"xl/worksheets/sheet{n}.xml" for n in (1, 3, 4, 5, 6, 7, 8)]
SST_EMPTY = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>')


def _shared_strings(xml: str) -> list[str]:
    items = re.findall(r"<si>(.*?)</si>", xml, re.DOTALL)
    return [unescape("".join(re.findall(r"<t\b[^>]*>(.*?)</t>", item, re.DOTALL))) for item in items]


def _inline(xml: str, strings: list[str]) -> str:
    def repl(m: re.Match) -> str:
        text = escape(strings[int(m.group(3))])
        return f'<c{m.group(1)}{m.group(2)} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    return re.sub(r'<c\b([^>]*?)\s+t="s"([^>]*)><v>(\d+)</v></c>', repl, xml)


def _row(number: int, values: list[str], span: int) -> str:
    cells = "".join(qb._cell(f"{qb._col_letter(i)}{number}", "text", v) for i, v in enumerate(values))
    return f'<row r="{number}" spans="1:{span}">{cells}</row>'


def _cols(widths: list[int]) -> str:
    return "<cols>" + "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1)) + "</cols>"


def build() -> None:
    with zipfile.ZipFile(SOURCE) as src:
        order = [i.filename for i in src.infolist()]
        files = {n: src.read(n) for n in order}
    text = lambda n: files[n].decode("utf-8")  # noqa: E731

    strings = _shared_strings(text("xl/sharedStrings.xml"))
    for name in SHEETS_WITH_STRINGS:
        files[name] = _inline(text(name), strings).encode("utf-8")
    files["xl/sharedStrings.xml"] = SST_EMPTY.encode("utf-8")

    # --- СписокСО: лист 1, таблица 1 ---
    sheet1 = text("xl/worksheets/sheet1.xml")
    sheet1 = _inline(sheet1, strings) if 't="s"' in sheet1 else sheet1
    sheet1 = re.sub(r' topLeftCell="[^"]*"', "", sheet1)
    sheet1 = re.sub(r'<selection\b[^>]*/>', '<selection activeCell="A1" sqref="A1"/>', sheet1)
    sheet1 = sheet1.replace("\\ВОР<", "\\СО<")
    files["xl/worksheets/sheet1.xml"] = qb._rewrite_sheet(sheet1, 15, [{}]).encode("utf-8")
    table1 = text("xl/tables/table1.xml").replace('name="СписокВОР"', 'name="СписокСО"').replace(
        'displayName="СписокВОР"', 'displayName="СписокСО"')
    files["xl/tables/table1.xml"] = qb._rewrite_table(table1, 15, 1, 16).encode("utf-8")

    # Кэш запроса СписокФайлов: пути из шаблона ВОР в шаблоне СО не нужны
    files["xl/worksheets/sheet6.xml"] = re.sub(
        r'<row r="2"[^>]*?(?:/>|>.*?</row>)', '<row r="2" spans="1:1"/>', text("xl/worksheets/sheet6.xml"),
        count=1, flags=re.DOTALL).encode("utf-8")

    # --- Справочник колонок: лист 3 (таблица ролей), лист 4 (результат запроса) ---
    columns = "".join(f'<tableColumn id="{i}" name="{r}"/>' for i, r in enumerate(SO_ROLES, 1))
    table3 = re.sub(r"<tableColumns\b.*?</tableColumns>",
                    lambda _m: f'<tableColumns count="{len(SO_ROLES)}">{columns}</tableColumns>',
                    text("xl/tables/table3.xml"), count=1, flags=re.DOTALL)
    sheet3 = re.sub(r"<cols>.*?</cols>", lambda _m: _cols([24, 40, 46, 36, 28, 26, 10, 26, 22]),
                    text("xl/worksheets/sheet3.xml"), count=1, flags=re.DOTALL)
    sheet3, table3 = qb._rewrite_reference(sheet3, table3, 1, SO_ROLES, SO_VARIANTS)
    files["xl/worksheets/sheet3.xml"], files["xl/tables/table3.xml"] = sheet3.encode("utf-8"), table3.encode("utf-8")

    pairs = [(role, v) for i in range(max(len(v) for v in SO_VARIANTS.values()))
             for role, v in ((r, SO_VARIANTS[r][i]) for r in SO_ROLES if i < len(SO_VARIANTS[r]))]
    last4 = len(pairs) + 1
    rows4 = [_row(1, ["Роль", "Вариант"], 2)] + [_row(n, [r, v], 2) for n, (r, v) in enumerate(pairs, 2)]
    sheet4 = re.sub(r"<sheetData>.*?</sheetData>", lambda _m: "<sheetData>" + "".join(rows4) + "</sheetData>",
                    text("xl/worksheets/sheet4.xml"), count=1, flags=re.DOTALL)
    sheet4 = re.sub(r'<dimension\b[^>]*/>', f'<dimension ref="A1:B{last4}"/>', sheet4, count=1)
    sheet4 = re.sub(r'<selection\b[^>]*/>', '<selection activeCell="A1" sqref="A1"/>', sheet4)
    files["xl/worksheets/sheet4.xml"] = sheet4.encode("utf-8")
    table4 = text("xl/tables/table4.xml").replace('ref="A1:B8"', f'ref="A1:B{last4}"')
    files["xl/tables/table4.xml"] = table4.encode("utf-8")

    # --- ФайлBinary: итоговая таблица запроса ---
    n = len(OUTPUT_COLUMNS)
    last = qb._col_letter(n - 1)
    head = _row(1, OUTPUT_COLUMNS, n)
    # Формат даты: dxf на столбце таблицы и стиль ячейки первой строки (Excel переносит их на результат запроса)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from make_vor_so_template import _add_date_dxf  # noqa: E402
    styles, date_style = qb._add_date_style(text("xl/styles.xml"))
    styles, date_dxf = _add_date_dxf(styles)
    files["xl/styles.xml"] = styles.encode("utf-8")
    date_col = qb._col_letter(OUTPUT_COLUMNS.index("ДатаИзм"))
    sheet9 = text("xl/worksheets/sheet9.xml")
    widths = [46, 14, 14, 12, 50, 9, 8, 50, 40, 22, 18, 12, 12, 14, 30, 60][:n]
    widths += [14] * (n - len(widths))
    sheet9 = re.sub(r"<cols>.*?</cols>", lambda _m: _cols(widths), sheet9, count=1, flags=re.DOTALL)
    sheet9 = re.sub(r"<sheetData>.*?</sheetData>",
                    lambda _m: f'<sheetData>{head}<row r="2" spans="1:{n}"><c r="{date_col}2" s="{date_style}"/></row></sheetData>', sheet9, count=1, flags=re.DOTALL)
    sheet9 = re.sub(r'<dimension\b[^>]*/>', f'<dimension ref="A1:{last}2"/>', sheet9, count=1)
    sheet9 = re.sub(r'<selection\b[^>]*/>', '<selection activeCell="A1" sqref="A1"/>', sheet9)
    files["xl/worksheets/sheet9.xml"] = sheet9.encode("utf-8")
    tcols = "".join(f'<tableColumn id="{i}" uniqueName="{i}" name="{c}" queryTableFieldId="{i}"'
                    + (f' dataDxfId="{date_dxf}"' if c == "ДатаИзм" else "") + "/>"
                    for i, c in enumerate(OUTPUT_COLUMNS, 1))
    files["xl/tables/table9.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="9" name="ФайлBinary" '
        f'displayName="ФайлBinary" ref="A1:{last}2" tableType="queryTable" totalsRowShown="0">'
        f'<autoFilter ref="A1:{last}2"/><tableColumns count="{n}">{tcols}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium7" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/></table>').encode("utf-8")
    fields = "".join(f'<queryTableField id="{i}" name="{c}" tableColumnId="{i}"/>' for i, c in enumerate(OUTPUT_COLUMNS, 1))
    files["xl/queryTables/queryTable6.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<queryTable xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" name="ExternalData_1" '
        'connectionId="21" autoFormatId="0" applyNumberFormats="1" applyBorderFormats="0" applyFontFormats="1" '
        'applyPatternFormats="1" applyAlignmentFormats="0" applyWidthHeightFormats="0">'
        f'<queryTableRefresh preserveSortFilterLayout="0" nextId="{n + 1}"><queryTableFields count="{n}">{fields}'
        '</queryTableFields></queryTableRefresh></queryTable>').encode("utf-8")

    # --- книга: имена листов, диапазоны скрытых имён, calcChain (формул больше нет) ---
    wb = text("xl/workbook.xml").replace('name="СписокВОР"', 'name="СписокСО"')
    wb = wb.replace("СправочникКолонок!$A$1:$B$8", f"СправочникКолонок!$A$1:$B${last4}")
    wb = wb.replace("ФайлBinary!$A$1:$R$788", f"ФайлBinary!$A$1:${last}$2")
    files["xl/workbook.xml"] = wb.encode("utf-8")
    files["docProps/app.xml"] = text("docProps/app.xml").replace("<vt:lpstr>СписокВОР<", "<vt:lpstr>СписокСО<").encode("utf-8")
    del files["xl/calcChain.xml"]
    rels = re.sub(r'<Relationship\b[^>]*calcChain[^>]*/>', "", text("xl/_rels/workbook.xml.rels"))
    files["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")
    types = re.sub(r'<Override\b[^>]*calcChain[^>]*/>', "", text("[Content_Types].xml"))
    files["[Content_Types].xml"] = types.encode("utf-8")

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in order:
            if name in files:
                dst.writestr(name, files[name])


def main() -> int:
    build()
    print("Книга собрана:", TARGET)
    cmd = [sys.executable, "-I", "-X", "utf8", os.path.join("scripts", "pq_sync.py"), "import",
           QUERIES, TARGET, "--add", "--prune"]
    code = subprocess.call(cmd)
    for leftover in (os.path.join("PQ", "СО", "шаблон СО.bak.xlsx"), os.path.join("PQ", "СО", "_import_report.xlsx")):
        if os.path.exists(leftover):
            os.remove(leftover)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
