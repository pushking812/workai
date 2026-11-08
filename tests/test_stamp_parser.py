"""Разбор штампа документа (Этап 1.4)."""

from __future__ import annotations

import os

import pytest

from core.parsers.stamp_parser import (
    LABEL_DOC_CODE,
    STAMP_CELLS,
    STAMP_OK,
    STAMP_PROFILE_FULL,
    STAMP_PROFILE_SHORT,
    STAMP_PROFILE_UNKNOWN,
    anchored_cell,
    detect_stamp_profile,
    read_title_blocks,
    find_doc_code,
    is_stamp_table,
    compare_with_filename,
    find_dates_in_filename,
    find_revision_in_filename,
    parse_date_from_filename,
    parse_doc_code,
    parse_revision_date,
    parse_stamp,
    read_stamp_values,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC_ES1 = os.path.join(ROOT, "16_ЕСТ-ПМ-80825-Р-1-ЭС1_ВОР.docx")
DOC_ISVN = os.path.join(ROOT, "ЕСТ-ПМ-80825-Р-1-ИСВН_ВОР.docx")


def _require(path: str) -> str:
    if not os.path.exists(path):
        pytest.skip("нет тестового документа " + os.path.basename(path))
    return path


def _stamp_grid(code: str = "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР") -> list[list[str]]:
    """Сетка штампа из описания: 11 строк снизу вверх, 10 столбцов."""
    grid = [[""] * 10 for _ in range(11)]
    # Строки идут сверху вниз: индекс 0 — строка 11 сетки.
    def put(row_number: int, column_number: int, value: str) -> None:
        grid[11 - row_number][column_number - 1] = value

    put(10, 7, code)
    put(9, 7, "Наименование титула")
    put(8, 1, "1")
    put(8, 2, "-")
    put(8, 3, "Нов.")
    put(8, 4, "069")
    put(8, 6, "06.02.26")
    put(7, 1, "Изм.")
    put(7, 2, "Кол.уч")
    put(7, 3, "Лист")
    put(7, 4, "№док.")
    put(7, 5, "Подп.")
    put(7, 6, "Дата")
    put(6, 8, "Стадия")
    put(6, 9, "Лист")
    put(6, 10, "Листов")
    put(5, 8, "Р")
    put(5, 9, "1.1")
    put(5, 10, "9")
    put(3, 8, "ООО «ЕСТ»")
    return grid


def test_cell_of_grid_coordinates() -> None:
    grid = _stamp_grid()
    assert anchored_cell(grid, 10, 7) == "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"
    assert anchored_cell(grid, 8, 1) == "1"
    assert anchored_cell(grid, 8, 6) == "06.02.26"
    assert anchored_cell(grid, 5, 8) == "Р"
    assert anchored_cell(grid, 5, 9) == "1.1"
    assert anchored_cell(grid, 5, 10) == "9"
    assert anchored_cell(grid, 11, 1) == ""
    assert anchored_cell([], 10, 7) == ""


def test_stamp_cells_have_description_coordinates() -> None:
    assert STAMP_CELLS[LABEL_DOC_CODE] == (10, 7)
    assert STAMP_CELLS["лист"] == (5, 9)
    assert STAMP_CELLS["листов"] == (5, 10)
    assert STAMP_CELLS["стадия"] == (5, 8)
    assert STAMP_CELLS["изм"] == (8, 1)
    assert STAMP_CELLS["дата"] == (8, 6)


def test_read_stamp_values_from_grid() -> None:
    values = read_stamp_values(_stamp_grid())
    assert values[LABEL_DOC_CODE] == "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"
    assert values["изм"] == "1"
    assert values["статуслиста"] == "Нов."
    assert values["дата"] == "06.02.26"
    assert values["стадия"] == "Р"
    assert values["лист"] == "1.1"
    assert values["листов"] == "9"


def test_is_stamp_table_requires_labels_and_code() -> None:
    grid = _stamp_grid()
    assert is_stamp_table(grid) is True
    assert find_doc_code(grid) == "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"

    no_code = [row[:] for row in grid]
    no_code[11 - 10][6] = ""
    assert find_doc_code(no_code) == ""
    assert is_stamp_table(no_code) is False

    empty: list[list[str]] = []
    assert is_stamp_table(empty) is False


def test_stamp_missing_file() -> None:
    stamp = parse_stamp(os.path.join(ROOT, "нет_такого_файла.docx"))
    assert stamp["doc_code"] == ""
    assert stamp["revision"] == "0"
    assert stamp["revision_date"] is None
    assert stamp["sheet"] is None
    assert stamp["sheets_total"] is None
    assert stamp["stamp_status"] == "MISSING"


def test_parse_revision_date_iso() -> None:
    assert parse_revision_date("01.08.25") == "2025-08-01"
    assert parse_revision_date("06.02.2026") == "2026-02-06"
    assert parse_revision_date("нет даты") is None


def test_parse_date_from_filename() -> None:
    assert parse_date_from_filename("ВОР 06.02.26.docx") == "2026-02-06"
    assert parse_date_from_filename("без даты.docx") is None


def test_parse_doc_code_parts() -> None:
    parsed = parse_doc_code("ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР")
    assert parsed["doc_code"] == "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"
    assert parsed["project_code"] == "ЕСТ-ПМ-80825-Р"
    assert parsed["section_code"] == "ИСВН"
    assert parsed["doc_type"] == "ВОР"


def test_parse_doc_code_without_type() -> None:
    parsed = parse_doc_code("ЕСТ-ПМ-80825-Р-1-ЭС1")
    assert parsed["doc_type"] == ""
    assert parsed["project_code"] == "ЕСТ-ПМ-80825-Р"
    assert parsed["section_code"] == "ЭС1"


def test_stamp_es1() -> None:
    stamp = parse_stamp(_require(DOC_ES1))
    message = str([stamp[k] for k in ("revision", "revision_date", "sheet", "sheets_total")])
    assert stamp["doc_code"] == "ЕСТ-ПМ-80825-Р-1-ЭС1.ВОР", message
    assert stamp["project_code"] == "ЕСТ-ПМ-80825-Р"
    assert stamp["section_code"] == "ЭС1"
    assert stamp["doc_type"] == "ВОР"
    assert stamp["revision"] == "1"
    assert stamp["revision_date"] == "2025-08-01"
    assert stamp["sheet"] == 1
    assert stamp["sheets_total"] == 5
    assert stamp["stamp_status"] == STAMP_OK


def test_stamp_isvn() -> None:
    stamp = parse_stamp(_require(DOC_ISVN))
    assert stamp["doc_code"] == "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"
    assert stamp["project_code"] == "ЕСТ-ПМ-80825-Р"
    assert stamp["section_code"] == "ИСВН"
    assert stamp["doc_type"] == "ВОР"
    assert stamp["revision"] == "1"
    assert stamp["revision_date"] == "2026-02-06"
    assert stamp["sheet"] == 1
    assert stamp["sheets_total"] == 9


def test_stamp_isvn_full_fields() -> None:
    stamp = parse_stamp(_require(DOC_ISVN))
    assert stamp["stage"] == "Р"
    assert stamp["organization"] == "ООО «Единые Системные Технологии»"
    assert stamp["object_name"].startswith("Реконструкция вестибюля станции «Фрунзенская»")
    assert stamp["title"].startswith("I этап строительства. Реконструкция вестибюля")
    assert stamp["document_name"] == "Система интеллектуального видеонаблюдения Ведомость объемов работ"
    by_position = {item["position"]: item for item in stamp["executors"]}
    assert by_position["Разработал"]["name"] == "Анисимов А.Ю."
    assert by_position["Разработал"]["date"] == "06.02.26"
    assert by_position["Проверил"]["name"] == "Шастов А.В."
    assert by_position["ГИП"]["name"] == "Шастов А.В."
    assert by_position["ГИП"]["signature"] == ""


def _title_rows(*blocks: str) -> list[list[str]]:
    rows = [["Заказчик: X", "", "", "", "", "", "Заказчик: X", "", "", ""]]
    rows.append([""] * 6 + ["ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"] + [""] * 3)
    for block in blocks:
        rows.append([""] * 6 + [block] + [""] * 3)
        rows.append([""] * 6 + [block] + [""] * 3)
    rows.append(["Изм.", "Кол.уч", "Лист", "№док", "Подп.", "Дата", "", "", "", ""])
    return rows


def test_detect_profile_full_and_short() -> None:
    full = _title_rows("Объект", "I этап строительства. Объект", "Документ ВОР")
    short = _title_rows("I этап строительства Наружное электроснабжение ВОР")
    assert detect_stamp_profile(full) == STAMP_PROFILE_FULL
    assert detect_stamp_profile(short) == STAMP_PROFILE_SHORT
    assert detect_stamp_profile(_title_rows("А", "Б")) == STAMP_PROFILE_UNKNOWN


def test_title_blocks_by_profile() -> None:
    full = read_title_blocks(_title_rows("Объект", "Титул", "Документ"))
    assert (full["объект"], full["наименование"], full["документ"]) == ("Объект", "Титул", "Документ")
    short = read_title_blocks(_title_rows("I этап строительства Электроснабжение ВОР"))
    assert short["объект"] == ""
    assert short["наименование"] == "I этап строительства"
    assert short["документ"] == "Электроснабжение ВОР"
    unknown = read_title_blocks(_title_rows("А", "Б"))
    assert unknown["профиль"] == STAMP_PROFILE_UNKNOWN
    assert unknown["наименование"] == unknown["документ"] == unknown["объект"] == ""


def test_stamp_profiles_of_real_documents() -> None:
    assert parse_stamp(_require(DOC_ISVN))["stamp_profile"] == STAMP_PROFILE_FULL
    assert parse_stamp(_require(DOC_ES1))["stamp_profile"] == STAMP_PROFILE_SHORT


def test_stamp_es1_full_fields() -> None:
    stamp = parse_stamp(_require(DOC_ES1))
    assert stamp["stage"] == "Р"
    assert stamp["organization"] == "ООО «Единые Системные Технологии»"
    assert stamp["object_name"] == ""
    assert stamp["title"] == "I этап строительства"
    assert stamp["document_name"] == "Наружное электроснабжение Ведомость объемов работ"
    names = {item["position"]: item["name"] for item in stamp["executors"]}
    assert names == {
        "Разработал": "Суханов О.В.",
        "Проверил": "Логунин А.Ю.",
        "ГИП": "Шастов А.В.",
    }
    assert all(item["date"] == "01.08.25" for item in stamp["executors"])


VOR_DIR = os.path.join(ROOT, "ВОР")


def test_find_dates_in_filename_formats() -> None:
    assert find_dates_in_filename("13_ЭК.ВОР__Изм.X от 2026.03.11 (поз.4).docx") == ["2026-03-11"]
    assert find_dates_in_filename("ЭС1_ВОР (Изм. 2025-08-01).docx") == ["2025-08-01"]
    assert find_dates_in_filename("ЭС1_ВОР Изм.2 от 17.06.26.docx") == ["2026-06-17"]
    assert find_dates_in_filename("АПТ.ВОР 1.02.2023.docx") == ["2023-02-01"]
    assert find_dates_in_filename("Прил 2. Изм.1 (1 этап) 2026-07.22.docx") == ["2026-07-22"]
    assert find_dates_in_filename("16. ВОР_Изм.1 от 2025.10._(Нов.)_Изм.1_1 от 2026.04.docx") == [
        "2025-10",
        "2026-04",
    ]
    assert find_dates_in_filename("13.2_Р-1-ИСВН.ВОР_изм.1.docx") == []
    assert find_dates_in_filename("Приложение 1. ВОР Изм.1 (2).docx") == []


def test_find_revision_in_filename() -> None:
    assert find_revision_in_filename("ЭС1_ВОР Изм.2 от 17.06.26.docx") == "2"
    assert find_revision_in_filename("Р-2-СКД.ВОР_изм. 1.docx") == "1"
    assert find_revision_in_filename("КАСДУ_изм1.docx") == "1"
    assert find_revision_in_filename("ЭК.ВОР__Изм.X от 2026.03.11.docx") == ""
    assert find_revision_in_filename("ЭС1_ВОР (Изм. 2025-08-01).docx") == ""
    assert find_revision_in_filename("АПТ.ВОР 1.02.2023.docx") == ""


def test_compare_with_filename_reports_not_fixes() -> None:
    issues = compare_with_filename("ВОР Изм.2 от 17.06.26.docx", "1", "2026-10-15")
    assert [item["field"] for item in issues] == ["revision_date", "revision"]
    assert issues[0]["stamp"] == "2026-10-15"
    assert issues[0]["filename"] == "2026-06-17"
    assert compare_with_filename("ВОР Изм.1 от 2026.02.docx", "1", "2026-02-11") == []
    assert compare_with_filename("ВОР.docx", "0", "2026-02-11") == []


def test_real_documents_discrepancies() -> None:
    xk = os.path.join(VOR_DIR, "13_ЕСТ-ПМ-80825-Р-1-ЭК.ВОР__Изм.X от 2026.03.11 (поз.4).docx")
    stamp = parse_stamp(_require(xk))
    assert stamp["revision_date"] == "2025-08-15"
    assert [item["field"] for item in stamp["discrepancies"]] == ["revision_date"]
    assert stamp["discrepancies"][0]["filename"] == "2026-03-11"

    es1 = os.path.join(VOR_DIR, "ЕСТ-ПМ-80825-Р-1-ЭС1_ВОР Изм.2 от 17.06.26.docx")
    stamp = parse_stamp(_require(es1))
    assert stamp["revision"] == "2"
    assert stamp["revision_date"] == "2026-10-15"
    assert [item["field"] for item in stamp["discrepancies"]] == ["revision_date"]

    matching = os.path.join(VOR_DIR, "13_ЕСТ-ПМ-80825-Р-1-ЭК.ВОР__Изм.1 от 2025.08.15.docx")
    assert parse_stamp(_require(matching))["discrepancies"] == []


RESULTS_PATH = os.path.join(ROOT, "vor_parsing_results.xlsx")
RESULT_FIELDS = (
    "doc_code",
    "project_code",
    "section_code",
    "doc_type",
    "revision",
    "revision_date",
    "sheet",
    "sheets_total",
    "stage",
    "organization",
    "object_name",
    "title",
    "document_name",
    "stamp_profile",
    "executors",
    "filename_dates",
    "discrepancies",
    "stamp_status",
    "stamp_raw",
)
EXCEL_CELL_LIMIT = 32000


def test_write_parsing_results_to_xlsx() -> None:
    """Записывает все распарсенные данные штампов в vor_parsing_results.xlsx."""
    import openpyxl

    documents = [path for path in (DOC_ES1, DOC_ISVN) if os.path.exists(path)]
    if os.path.isdir(VOR_DIR):
        documents += sorted(
            os.path.join(VOR_DIR, name) for name in os.listdir(VOR_DIR) if name.lower().endswith(".docx")
        )
    if not documents:
        pytest.skip("нет тестовых документов")

    if os.path.exists(RESULTS_PATH):
        workbook = openpyxl.load_workbook(RESULTS_PATH)
        if "parsing_results" in workbook.sheetnames:
            del workbook["parsing_results"]
        sheet = workbook.create_sheet("parsing_results", 0)
    else:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "parsing_results"
    sheet.append(["file", *RESULT_FIELDS])
    for path in documents:
        stamp = parse_stamp(path)
        row = [os.path.basename(path)]
        for field in RESULT_FIELDS:
            value = stamp[field]
            if field == "executors":
                value = "; ".join(
                    ", ".join(item[key] for key in ("position", "name", "signature", "date"))
                    for item in value
                )
            elif field == "filename_dates":
                value = ", ".join(value)
            elif field == "discrepancies":
                value = "; ".join(item["message"] for item in value)
            if isinstance(value, str) and len(value) > EXCEL_CELL_LIMIT:
                value = value[:EXCEL_CELL_LIMIT]
            row.append(value)
        sheet.append(row)
    workbook.save(RESULTS_PATH)

    saved = openpyxl.load_workbook(RESULTS_PATH)
    saved_sheet = saved["parsing_results"]
    assert saved_sheet.max_row == len(documents) + 1
    header = [cell.value for cell in saved_sheet[1]]
    assert header == ["file", *RESULT_FIELDS]

    assert stamp["stamp_status"] == STAMP_OK


def test_doc_code_spaces_and_missing_type():
    from core.parsers.stamp_parser import is_bare_doc_code, normalize_doc_code

    # Пробел после дефиса (штампы КЖ: `Р-1- АСТУЭ.КЖ`).
    assert normalize_doc_code("ЕСТ-ПМ-80825-Р-1- АСТУЭ.КЖ") == "ЕСТ-ПМ-80825-Р-1-АСТУЭ.КЖ"
    rows = [["", "", "", "", "", "", "ЕСТ-ПМ-80825-Р-1- АК.КЖ"]]
    assert find_doc_code(rows) == "ЕСТ-ПМ-80825-Р-1-АК.КЖ"
    # Шифр без типа документа берётся как есть; тип в parse_stamp будет XN.
    assert parse_doc_code("ЕСТ-ПМ-80825-Р-1-АСДУ")["doc_type"] == ""
    assert is_bare_doc_code("ЕСТ-ПМ-80825-Р-1-АСДУ")
    assert find_doc_code([["", "ЕСТ-ПМ-80825-Р-1-АСДУ"]]) == "ЕСТ-ПМ-80825-Р-1-АСДУ"
    # Короткие значения штампа шифром не считаются.
    assert not is_bare_doc_code("Р-1")
    assert find_doc_code([["Р", "1", "Лист"]]) == ""
