"""Чтение КЖ и СО из docx в строки для core/cable_link.py (без БД и Excel)."""
from core.parsers.docx_parser import extract_tables_from_docx
from core.parsers.header_profiles import parse_table


def _col(headers, suffix, prefer="ПоПроекту|"):
    # «ПоПроекту|Марка» и «КабельПровод|ПоПроекту|Марка»; колонки проходов через трубу и «Проложен» не берём.
    found = [i for i, h in enumerate(headers) if h == prefer + suffix or h.endswith("|" + prefer + suffix)] or \
            [i for i, h in enumerate(headers)
             if (h.endswith("|" + suffix) or h == suffix) and "ПроходЧерез" not in h and "Проложен" not in h]
    return found[0] if found else None


def project_code(doc_code):
    """Шифр системы из шифра документа: 'ЕСТ-ПМ-80825-Р-2-СДС.КЖ' -> 'ЕСТ-ПМ-80825-Р-2-СДС'."""
    return (doc_code or "").strip().rsplit(".", 1)[0] if "." in (doc_code or "") else (doc_code or "").strip()


def read_kzh(path, with_code=True):
    """Строки КЖ {"Марка", "Сечение", "Длина", "Шифр"} из всех таблиц с колонками марки, сечения и длины «по проекту».
    Шифр - шифр системы из штампа (как ШифрПроекта в СО); пустой, если штамп не прочитан."""
    code = ""
    if with_code:
        from core.parsers.stamp_parser import parse_stamp
        code = project_code(parse_stamp(path).get("doc_code"))
    out = []
    for table in extract_tables_from_docx(path):
        pt = parse_table(table)
        im, isec, il = (_col(pt.headers, s) for s in ("Марка", "КолЧислоИСечЖил", "ДлинаМ"))
        if None in (im, isec, il):
            continue
        for r in pt.rows:
            out.append({"Марка": r[im], "Сечение": r[isec], "Длина": r[il], "Шифр": code})
    return out


def so_rows_from_strings(rows):
    """Строки СО_Строки (книга СО/ВОР+СО, имена столбцов PQ) -> {"Наименование", "Тип", "Ед", "Кол", "Шифр"}.
    Как в запросе СО_Строки: строки без ИдСтроки и без NПП не берутся."""
    out = []
    for r in rows:
        if not r.get("ИдСтроки") or not str(r.get("NПП") or "").strip():
            continue
        out.append({"Наименование": r.get("НаименованиеИТехХар"), "Тип": r.get("ТипМаркаОбозначение"),
                    "Ед": r.get("ЕдИзм"), "Кол": r.get("КолВо"), "Шифр": r.get("ШифрПроекта") or ""})
    return out


def read_so_book(path, sheet="ФайлBinary"):
    """Строки СО из книги СО (лист ФайлBinary) - то же, что читает общая книга ВОР+СО."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        it = wb[sheet].iter_rows(values_only=True)
        head = next(it)
        return so_rows_from_strings(dict(zip(head, row)) for row in it)
    finally:
        wb.close()


def read_so(path):
    """Строки СО {"Наименование", "Тип", "Ед", "Кол"}."""
    out = []
    for table in extract_tables_from_docx(path):
        pt = parse_table(table)
        # Шапки разных СО: «Ед. изме- ре- ния», «Коли- чест- во» - склеиваем переносы.
        h = [x.lower().replace("- ", "").replace(" ", "") for x in pt.headers]
        try:
            iname = next(i for i, x in enumerate(h) if x.startswith("наименован"))
            itype = next(i for i, x in enumerate(h) if x.startswith("тип"))
            iunit = next(i for i, x in enumerate(h) if x.startswith("ед"))
            iqty = next(i for i, x in enumerate(h) if x.startswith("кол"))
        except StopIteration:
            continue
        for r in pt.rows:
            out.append({"Наименование": r[iname], "Тип": r[itype], "Ед": r[iunit], "Кол": r[iqty]})
    return out
