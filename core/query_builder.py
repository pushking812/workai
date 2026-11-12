"""«Сформировать запросы»: копия шаблона Power Query с таблицей списка CSV.

Для типа документа есть книга-шаблон (ВОР и СО). Из неё делается копия,
и в таблицу-список (`СписокВОР` / `СписокСО` на одноимённом листе) записывается по строке
на каждый CSV выбранных файлов: путь к CSV, метаданные штампа и сведения об
исходном документе. Всё остальное в книге (запросы, остальные листы) не меняется:
книга правится как архив, а не через openpyxl, который теряет блок Power Query.
"""

from __future__ import annotations

import csv
import os
import re
import zipfile
from datetime import date, datetime
from typing import Any
from xml.sax.saxutils import escape, unescape

from core import database, header_dictionary, kits
from core.doc_types import SPEC, VOR
from core.transformer.fuzzy_matcher import find_best_match

QUERIES_DIR = os.path.join("data", "queries")

# Тип документа -> шаблон. Новые типы добавляются здесь же.
TEMPLATES: dict[str, dict[str, str]] = {
    VOR: {
        "path": os.path.join("PQ", "ВОР", "шаблон ВОР.xlsx"),
        "sheet": "СписокВОР",
        "table": "СписокВОР",
        # Справочник колонок: роли (столбцы таблицы) и варианты шапки (строки).
        "ref_sheet": "Справочники",
        "ref_table": "СправочникКолонок",
    },
    # Шаблон СО собирает scripts/make_so_template.py из шаблона ВОР: без разбора ссылок и номеров.
    SPEC: {
        "path": os.path.join("PQ", "СО", "шаблон СО.xlsx"),
        "sheet": "СписокСО",
        "table": "СписокСО",
        "ref_sheet": "Справочники",
        "ref_table": "СправочникКолонок",
    },
}

# Имя роли в книге, если оно отличается от канонического имени в БД: запросы
# шаблона (`ФайлBinary`) ждут именно эти имена колонок.
ROLE_ALIASES: dict[str, dict[str, str]] = {
    VOR: {
        "NЛСР": "NВЛСР",
        "ФормулаРасчета": "ФормулаРасРасОбъРабИРасМат",
    },
}

# Столбцы таблицы: имя, поле строки, вид значения. Первые пять — как в шаблоне
# (их читают запросы), остальные добавлены для сведений об исходном файле.
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("ШифрПроекта", "project_doc_code", "text"),
    ("НомИзмПроекта", "revision", "int"),
    ("ДатаИзм", "revision_date", "date"),
    ("ПутьФайла", "csv_path", "text"),
    ("Загружать", "load", "int"),
    ("ИмяФайла", "filename", "text"),
    ("ПутьИсходногоФайла", "path", "text"),
    ("Таблица", "table_no", "int"),
    ("ТипДокумента", "doc_type", "text"),
    ("КодПроекта", "project_code", "text"),
    ("КодРаздела", "section_code", "text"),
    ("Лист", "sheet", "int"),
    ("Листов", "sheets_total", "int"),
    ("ГруппаВариантов", "variant_group", "text"),
    ("Актуален", "is_current", "int"),
    ("Хэш", "hash", "text"),
    ("СхемаШапки", "schema_hash", "text"),
    ("ИдФайла", "file_id", "int"),
)

_TABLE_NO = re.compile(r"_table_(\d+)\.csv$", re.IGNORECASE)
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DATE_STYLE = 1  # индекс стиля «дата» в шаблоне (им оформлен столбец ДатаИзм)
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


class QueryBuildError(Exception):
    pass


def _col_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _csv_list(joined: str | None) -> list[str]:
    return [p.strip() for p in str(joined or "").split(";") if p.strip()]


def _project_doc_code(row: dict[str, Any]) -> str:
    """Шифр без типа документа: `…-СС.ВОР` -> `…-СС` (как в шаблоне)."""
    code = row.get("doc_code") or ""
    doc_type = row.get("doc_type") or ""
    suffix = "." + doc_type
    if doc_type and code.upper().endswith(suffix.upper()):
        code = code[: -len(suffix)]
    return code


def list_rows(file_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Строки списка для одного файла: по одной на каждый CSV (таблицу документа)."""
    rows = []
    # Шифр, номер и дата изменения — комплекта (путь + дата изменения из штампа),
    # а не сырые значения штампа: так ВОР и СО одного комплекта дают один ключ связи.
    kit = kits.kit_info(file_row)
    for csv_path in _csv_list(file_row.get("csv_path")):
        match = _TABLE_NO.search(csv_path)
        rows.append({
            **file_row,
            "file_id": file_row.get("id"),
            "project_doc_code": kit["kit_code"] or _project_doc_code(file_row),
            # Без папки шифра номер изменения остаётся как в штампе (может быть не числом).
            "revision": kit["kit_revision"] if kits.folder_kit(file_row.get("path") or "") else file_row.get("revision"),
            "revision_date": kit["kit_date"] or file_row.get("revision_date"),
            "kit_key": (kit["kit_code"], kit["kit_revision"], str(kit["kit_date"] or "")[:10]),
            "csv_path": os.path.abspath(csv_path),
            "table_no": int(match.group(1)) if match else None,
            "load": 1,
        })
    return rows


def _excel_date(value: Any) -> int | None:
    try:
        return (date.fromisoformat(str(value)[:10]) - date(1899, 12, 30)).days
    except ValueError:
        return None


def _cell(ref: str, kind: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    if kind == "date":
        serial = _excel_date(value)
        return f'<c r="{ref}" s="{_DATE_STYLE}"><v>{serial}</v></c>' if serial else ""
    if kind == "int":
        try:
            return f'<c r="{ref}"><v>{int(value)}</v></c>'
        except (TypeError, ValueError):
            pass  # не число (например, «Изм.X») — пишем как текст
    text = escape(_BAD_XML.sub("", str(value)))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = zf.read("xl/workbook.xml").decode("utf-8")
    match = re.search(r'<sheet\b[^>]*\bname="%s"[^>]*/>' % re.escape(escape(sheet_name)), workbook)
    if not match:
        raise QueryBuildError(f"В шаблоне нет листа «{sheet_name}»")
    rid = re.search(r'\br:id="([^"]+)"', match.group(0)).group(1)
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    for rel in re.findall(r"<Relationship\b[^>]*/>", rels):
        if re.search(r'\bId="%s"' % re.escape(rid), rel):
            target = re.search(r'\bTarget="([^"]+)"', rel).group(1)
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    raise QueryBuildError(f"Не найден файл листа «{sheet_name}»")


def _table_path(zf: zipfile.ZipFile, sheet_file: str, table_name: str) -> str:
    rels_name = "xl/worksheets/_rels/%s.rels" % os.path.basename(sheet_file)
    if rels_name not in zf.namelist():
        raise QueryBuildError(f"На листе нет таблицы «{table_name}»")
    rels = zf.read(rels_name).decode("utf-8")
    for target in re.findall(r'\bTarget="([^"]*tables/[^"]+)"', rels):
        path = "xl/" + target.replace("../", "")
        head = zf.read(path).decode("utf-8")
        if re.search(r'<table\b[^>]*\bname="%s"' % re.escape(table_name), head):
            return path
    raise QueryBuildError(f"На листе нет таблицы «{table_name}»")


def _rewrite_table(xml: str, header_row: int, count: int, last_row: int) -> str:
    last_col = _col_letter(len(COLUMNS) - 1)
    ref = f"A{header_row}:{last_col}{last_row}"
    old = dict(re.findall(r'<tableColumn\b[^>]*?\bname="([^"]+)"[^>]*?\bdataDxfId="(\d+)"', xml))
    old.update({n: d for d, n in re.findall(r'<tableColumn\b[^>]*?\bdataDxfId="(\d+)"[^>]*?\bname="([^"]+)"', xml)})
    columns = []
    for index, (name, _field, _kind) in enumerate(COLUMNS, 1):
        dxf = f' dataDxfId="{old[name]}"' if name in old else ""
        columns.append(f'<tableColumn id="{index}" name="{name}"{dxf}/>')
    xml = re.sub(r'(<table\b[^>]*?\bref=")[^"]*(")', lambda m: m.group(1) + ref + m.group(2), xml, count=1)
    xml = re.sub(r"<autoFilter\b[^>]*/>", f'<autoFilter ref="{ref}"/>', xml, count=1)
    return re.sub(
        r"<tableColumns\b.*?</tableColumns>",
        f'<tableColumns count="{len(COLUMNS)}">{"".join(columns)}</tableColumns>',
        xml, count=1, flags=re.DOTALL,
    )


def _rewrite_sheet(xml: str, header_row: int, rows: list[dict[str, Any]]) -> str:
    kept = [
        m.group(0) for m in re.finditer(r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>.*?</row>)', xml, re.DOTALL)
        if int(re.search(r'\br="(\d+)"', m.group(0)).group(1)) < header_row
    ]
    span = f'spans="1:{len(COLUMNS)}"'
    header = "".join(_cell(f"{_col_letter(i)}{header_row}", "text", name) for i, (name, _f, _k) in enumerate(COLUMNS))
    body = [f'<row r="{header_row}" {span}>{header}</row>']
    for offset, item in enumerate(rows, 1):
        number = header_row + offset
        cells = "".join(
            _cell(f"{_col_letter(i)}{number}", kind, item.get(field))
            for i, (_n, field, kind) in enumerate(COLUMNS)
        )
        body.append(f'<row r="{number}" {span}>{cells}</row>')
    sheet_data = "<sheetData>" + "".join(kept) + "".join(body) + "</sheetData>"
    xml = re.sub(r"<sheetData\b.*?</sheetData>|<sheetData\s*/>", lambda _m: sheet_data, xml, count=1, flags=re.DOTALL)
    last = f"{_col_letter(len(COLUMNS) - 1)}{header_row + len(rows)}"
    xml = re.sub(r'<dimension\b[^>]*/>', f'<dimension ref="A1:{last}"/>', xml, count=1)
    # Ширина новых столбцов; существующие (A–E) остаются как в шаблоне.
    widths = {5: 30, 6: 60, 7: 10, 8: 14, 9: 14, 10: 14, 11: 8, 12: 9, 13: 16, 14: 10, 15: 66, 16: 66, 17: 10}
    extra = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{widths.get(i, 14)}" customWidth="1"/>'
        for i in range(5, len(COLUMNS))
    )
    return re.sub(r"</cols>", lambda _m: extra + "</cols>", xml, count=1)


def _read_csv_header(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        first = next(csv.reader(handle, delimiter=";"), [])
    return [cell.strip() for cell in first if cell.strip()]


def collect_variants(
    connection: Any,
    csv_paths: list[str],
    roles: list[str],
    aliases: dict[str, str] | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Варианты шапки по ролям: заголовки CSV, сопоставленные с каноническими именами.

    Сопоставление делает Python (`find_best_match`: справочник синонимов, затем
    нечёткий поиск), Excel потом ищет в справочнике точное совпадение с шапкой
    CSV. Возвращает {роль: [вариант, ...]} и список заголовков без роли.
    """
    aliases = aliases or {}
    ignored = header_dictionary.ignored_keys(connection)
    found: dict[str, list[str]] = {}
    unresolved: list[str] = []
    seen: dict[str, str | None] = {}
    for path in csv_paths:
        for header in _read_csv_header(path):
            if database.synonym_key(header) in ignored:
                continue  # решено игнорировать всегда: остаётся под сырым именем
            if header not in seen:
                seen[header] = _resolve_role(connection, header, roles, aliases)
            role = seen[header]
            if role is None:
                if header not in unresolved:
                    unresolved.append(header)
            elif header not in found.setdefault(role, []):
                found[role].append(header)
    return found, unresolved


def _resolve_role(connection: Any, header: str, roles: list[str], aliases: dict[str, str]) -> str | None:
    match = find_best_match(connection, header)
    if match["requires_manual_review"] or not match["suggested_canonical"]:
        return None
    role = aliases.get(match["suggested_canonical"], match["suggested_canonical"])
    return role if role in roles else None


def _looks_like_data_row(cells: list[str]) -> bool:
    """Первая ячейка «шапки» — число: скорее всего, это строка данных."""
    return bool(cells) and bool(re.fullmatch(r"\d+([.,]\d+)?", cells[0]))


def analyze_headers(
    file_ids: list[int],
    db_path: str | None = None,
    templates: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Заголовки выбранных файлов, для которых нет роли (до сборки книги).

    Возвращает {"roles": [...], "unresolved": [{header, count, suspicious, files:
    [{id, filename, column}], candidates: [{canonical, score}]}]}. Роли — столбцы
    справочника шаблона и роли, заведённые пользователем.
    """
    templates = templates or TEMPLATES
    connection = database.init_db(db_path)
    try:
        ignored = header_dictionary.ignored_keys(connection)
        extra = header_dictionary.user_roles(connection)
        items: dict[str, dict[str, Any]] = {}
        all_roles: list[str] = []
        for file_id in dict.fromkeys(int(i) for i in file_ids or []):
            row = database.get_file_by_id(connection, file_id)
            if row is None or row.get("doc_type") not in templates:
                continue
            spec = templates[row["doc_type"]]
            if not spec.get("ref_sheet"):
                continue
            roles = _template_roles(spec) + [r for r in extra if r not in _template_roles(spec)]
            all_roles.extend(r for r in roles if r not in all_roles)
            aliases = ROLE_ALIASES.get(row["doc_type"]) or {}
            for csv_path in _csv_list(row.get("csv_path")):
                if not os.path.isfile(csv_path):
                    continue
                with open(csv_path, encoding="utf-8-sig", newline="") as handle:
                    first = [c.strip() for c in next(csv.reader(handle, delimiter=";"), [])]
                suspicious = _looks_like_data_row([c for c in first if c])
                for column, header in enumerate(first, 1):
                    if not header or database.synonym_key(header) in ignored:
                        continue
                    if _resolve_role(connection, header, roles, aliases) is not None:
                        continue
                    item = items.setdefault(header, {"header": header, "count": 0, "suspicious": False,
                                                    "files": []})
                    item["count"] += 1
                    item["suspicious"] = item["suspicious"] or suspicious
                    entry = {"id": file_id, "filename": row.get("filename"),
                             "path": row.get("path") or "", "column": column}
                    if entry not in item["files"]:
                        item["files"].append(entry)
        unresolved = list(items.values())
        for item in unresolved:
            item["candidates"] = header_dictionary.suggest(connection, item["header"], all_roles)
        return {"roles": all_roles, "unresolved": unresolved}
    finally:
        connection.close()


def _template_roles(spec: dict[str, str]) -> list[str]:
    """Роли шаблона: столбцы таблицы справочника колонок (первая строка листа)."""
    import openpyxl

    wb = openpyxl.load_workbook(spec["path"], read_only=True)
    try:
        ws = wb[spec["ref_sheet"]]
        return [c for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True)) if c]
    finally:
        wb.close()


def _table_columns(table_xml: str) -> list[str]:
    block = re.search(r"<tableColumns\b.*?</tableColumns>", table_xml, re.DOTALL).group(0)
    return [unescape(n) for n in re.findall(r'<tableColumn\b[^>]*?\bname="([^"]*)"', block)]


def _existing_variants(template: str, sheet: str, roles: list[str], header_row: int) -> dict[str, list[str]]:
    """Варианты, уже записанные в шаблоне (читаем значения, книгу не меняем)."""
    import openpyxl

    wb = openpyxl.load_workbook(template, read_only=True, data_only=True)
    try:
        ws = wb[sheet]
        result: dict[str, list[str]] = {role: [] for role in roles}
        for row in ws.iter_rows(min_row=header_row + 1, max_col=len(roles), values_only=True):
            for role, value in zip(roles, row):
                text = str(value).strip() if value is not None else ""
                if text and text not in result[role]:
                    result[role].append(text)
        return result
    finally:
        wb.close()


def _rewrite_reference(sheet_xml: str, table_xml: str, header_row: int, roles: list[str],
                       variants: dict[str, list[str]]) -> tuple[str, str]:
    """Таблица справочника: строка заголовка (роли) и по строке на номер варианта."""
    depth = max([len(v) for v in variants.values()] + [1])
    span = f'spans="1:{len(roles)}"'
    kept = [
        m.group(0) for m in re.finditer(r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>.*?</row>)', sheet_xml, re.DOTALL)
        if int(re.search(r'\br="(\d+)"', m.group(0)).group(1)) < header_row
    ]
    header = "".join(_cell(f"{_col_letter(i)}{header_row}", "text", r) for i, r in enumerate(roles))
    body = [f'<row r="{header_row}" {span}>{header}</row>']
    for offset in range(depth):
        number = header_row + 1 + offset
        cells = "".join(
            _cell(f"{_col_letter(i)}{number}", "text", variants.get(r, [])[offset] if offset < len(variants.get(r, [])) else None)
            for i, r in enumerate(roles)
        )
        body.append(f'<row r="{number}" {span}>{cells}</row>')
    data = "<sheetData>" + "".join(kept) + "".join(body) + "</sheetData>"
    last = f"{_col_letter(len(roles) - 1)}{header_row + depth}"
    sheet_xml = re.sub(r"<sheetData\b.*?</sheetData>|<sheetData\s*/>", lambda _m: data, sheet_xml, count=1, flags=re.DOTALL)
    sheet_xml = re.sub(r"<dimension\b[^>]*/>", f'<dimension ref="A1:{last}"/>', sheet_xml, count=1)
    ref = f"A{header_row}:{last}"
    table_xml = re.sub(r'(<table\b[^>]*?\bref=")[^"]*(")', lambda m: m.group(1) + ref + m.group(2), table_xml, count=1)
    table_xml = re.sub(r"<autoFilter\b[^>]*/>", f'<autoFilter ref="{ref}"/>', table_xml, count=1)
    old_roles = _table_columns(table_xml)
    new_roles = [r for r in roles if r not in old_roles]
    if new_roles:
        top = max([int(i) for i in re.findall(r'<tableColumn\b[^>]*?\bid="(\d+)"', table_xml)] + [0])
        added = "".join(
            f'<tableColumn id="{top + n}" name="{escape(r, {chr(34): "&quot;"})}"/>'
            for n, r in enumerate(new_roles, 1)
        )
        table_xml = table_xml.replace("</tableColumns>", added + "</tableColumns>", 1)
        table_xml = re.sub(r'(<tableColumns\b[^>]*\bcount=")\d+', lambda m: m.group(1) + str(len(roles)),
                           table_xml, count=1)
    return sheet_xml, table_xml


def fill_template(
    template: str,
    output: str,
    rows: list[dict[str, Any]],
    sheet: str,
    table: str,
    reference: dict[str, Any] | None = None,
) -> None:
    """Копирует шаблон в `output` и заменяет строки таблицы `table` на листе `sheet`.

    `reference` (необязательно): {"sheet", "table", "variants": {роль: [вариант]}}.
    Варианты добавляются к уже записанным в справочнике шаблона.
    """
    if not rows:
        raise QueryBuildError("Нет строк для списка")
    if not os.path.isfile(template):
        raise QueryBuildError(f"Шаблон не найден: {template}")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    tmp = output + ".tmp"
    try:
        with zipfile.ZipFile(template) as src:
            sheet_file = _sheet_path(src, sheet)
            table_file = _table_path(src, sheet_file, table)
            table_xml = src.read(table_file).decode("utf-8")
            ref = re.search(r'<table\b[^>]*?\bref="[A-Z]+(\d+):', table_xml)
            if not ref:
                raise QueryBuildError("Не удалось прочитать диапазон таблицы")
            header_row = int(ref.group(1))
            new_sheet = _rewrite_sheet(src.read(sheet_file).decode("utf-8"), header_row, rows)
            new_table = _rewrite_table(table_xml, header_row, len(rows), header_row + len(rows))
            replaced = {sheet_file: new_sheet, table_file: new_table}
            if reference:
                ref_sheet_file = _sheet_path(src, reference["sheet"])
                ref_table_file = _table_path(src, ref_sheet_file, reference["table"])
                ref_table_xml = src.read(ref_table_file).decode("utf-8")
                ref_head = re.search(r'<table\b[^>]*?\bref="[A-Z]+(\d+):', ref_table_xml)
                if not ref_head:
                    raise QueryBuildError("Не удалось прочитать диапазон справочника колонок")
                ref_row = int(ref_head.group(1))
                table_roles = _table_columns(ref_table_xml)
                variants = _existing_variants(template, reference["sheet"], table_roles, ref_row)
                # Роли, заведённые пользователем, добавляются столбцами справочника.
                roles = table_roles + [r for r in reference.get("extra_roles", []) if r not in table_roles]
                for role in roles:
                    variants.setdefault(role, [])
                for role, names in reference["variants"].items():
                    for name in names:
                        if role in variants and name not in variants[role]:
                            variants[role].append(name)
                replaced[ref_sheet_file], replaced[ref_table_file] = _rewrite_reference(
                    src.read(ref_sheet_file).decode("utf-8"), ref_table_xml, ref_row, roles, variants)
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename in replaced:
                        data = replaced[info.filename].encode("utf-8")
                    dst.writestr(info, data)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def build_queries(
    file_ids: list[int],
    db_path: str | None = None,
    templates: dict[str, dict[str, str]] | None = None,
    out_dir: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Формирует по одной книге на каждый тип документа, для которого есть шаблон.

    В книгу типа попадают документы всех выбранных комплектов.

    Файлы других типов, без CSV или с удалённым CSV пропускаются и попадают в
    `skipped` с причиной.
    """
    templates = templates or TEMPLATES
    out_dir = out_dir or QUERIES_DIR
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    by_type: dict[str, list[dict[str, Any]]] = {}
    skipped: list[dict[str, Any]] = []
    connection = database.init_db(db_path)
    try:
        for file_id in dict.fromkeys(int(i) for i in file_ids or []):
            row = database.get_file_by_id(connection, file_id)
            if row is None:
                continue
            reason = None
            if row.get("doc_type") not in templates:
                reason = "нет шаблона для типа «%s»" % (row.get("doc_type") or "не определён")
            elif not _csv_list(row.get("csv_path")):
                reason = "у файла нет CSV (сначала «Сохранить»)"
            elif not all(os.path.isfile(p) for p in _csv_list(row.get("csv_path"))):
                reason = "CSV не найден на диске"
            if reason:
                skipped.append({"id": file_id, "filename": row.get("filename"), "reason": reason})
                continue
            for item in list_rows(row):
                # Все документы типа — в одну книгу; комплект (шифр, изм., дата)
                # остаётся в столбцах ШифрПроекта/НомИзмПроекта/ДатаИзм.
                by_type.setdefault(row["doc_type"], []).append(item)
    finally:
        connection.close()

    books = []
    for doc_type, rows in by_type.items():
        spec = templates[doc_type]
        kit_keys = list(dict.fromkeys(r["kit_key"] for r in rows))
        output = os.path.join(out_dir, f"{doc_type}_{stamp}.xlsx")
        reference, unresolved = None, []
        if spec.get("ref_sheet"):
            reference, unresolved = _reference_for(spec, doc_type, rows, db_path)
        fill_template(spec["path"], output, rows, spec["sheet"], spec["table"], reference)
        books.append({"doc_type": doc_type, "path": os.path.abspath(output),
                      "kits": [{"code": k[0], "revision": k[1], "date": k[2]} for k in kit_keys],
                      "files": len({r["file_id"] for r in rows}), "rows": len(rows),
                      "unresolved_headers": unresolved,
                      "ambiguous_versions": find_ambiguous_versions(rows)})
    return {"books": books, "skipped": skipped}


def _kit_label(kit_key: tuple) -> str:
    """Часть имени книги: шифр_Изм<N>_<дата> без символов, запрещённых в именах файлов."""
    code, revision, date_text = kit_key
    label = f"{code}_Изм{revision}" + (f"_{str(date_text)[:10]}" if date_text else "")
    return re.sub(r'[\\/:*?"<>|\s]+', "_", label).strip("_") or "комплект"


def find_ambiguous_versions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Файлы с одинаковой версией (шифр, номер изменения, дата изменения).

    По такой тройке ВОР связывается с СО; если у неё больше одного файла, связь
    неоднозначна: пользователь должен выбрать нужный файл или убрать лишний.
    """
    groups: dict[tuple, dict[int, str]] = {}
    for r in rows:
        key = (r.get("project_doc_code") or "", str(r.get("revision") or ""), str(r.get("revision_date") or "")[:10])
        groups.setdefault(key, {})[r["file_id"]] = r.get("filename") or ""
    return [
        {"doc_code": k[0], "revision": k[1], "revision_date": k[2],
         "files": [{"id": i, "filename": n} for i, n in files.items()]}
        for k, files in groups.items() if len(files) > 1
    ]


def _reference_for(spec: dict[str, str], doc_type: str, rows: list[dict[str, Any]],
                   db_path: str | None) -> tuple[dict[str, Any], list[str]]:
    """Варианты шапки для справочника колонок по CSV из списка."""
    template_roles = _template_roles(spec)
    paths = list(dict.fromkeys(r["csv_path"] for r in rows))
    connection = database.init_db(db_path)
    try:
        extra = [r for r in header_dictionary.user_roles(connection) if r not in template_roles]
        variants, unresolved = collect_variants(
            connection, paths, template_roles + extra, ROLE_ALIASES.get(doc_type))
    finally:
        connection.close()
    return {"sheet": spec["ref_sheet"], "table": spec["ref_table"], "variants": variants,
            "extra_roles": extra}, unresolved
