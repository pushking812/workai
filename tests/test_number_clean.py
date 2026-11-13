from core import kits
from core.parsers.header_profiles import clean_row_numbers, parse_table, suspect_row_numbers


def test_row_numbers_not_modified():
    rows = [["18)", "Работа"], ["1.2.", "x"]]
    assert clean_row_numbers(["№ п/п", "Наименование"], rows) == rows


def test_suspect_row_numbers():
    rows = [["18)", "Работа"], ["1.2.", "x"], ["", "Раздел"], ["Итого", "y"], ["№ 5", "z"]]
    assert suspect_row_numbers(["№ п/п", "Наименование"], rows) == ["18)", "№ 5"]


def test_suspect_other_columns_ignored():
    assert suspect_row_numbers(["Наименование", "Ед. изм."], [["a1)", "b)"]]) == []


def test_repeated_item_number_moves_from_name_even_below_threshold():
    rows = [["1", "2", "3"]]
    for i in range(1, 9):
        rows.append([f"13.{i}", f"Прибор {i}", "шт"])
    rows += [
        ["14.1", "Кабель 1x2", "м"],
        ["14.1", "Кабель 1x2", "м"],
        ["", "14.1 Кабель 1x2", "м"],
        ["", "14.1 Кабель 1x2", "м"],
        ["14.2", "Кабель 3x2", "м"],
        ["", "14.2 Кабель 3x2", "м"],
    ]
    parsed = parse_table([["Поз.", "Наименование", "Ед. изм."]] + rows)
    tail = parsed.rows[-6:]
    assert [r[0] for r in tail] == ["14.1", "14.1", "14.1", "14.1", "14.2", "14.2"]
    assert {r[1] for r in tail[:4]} == {"Кабель 1x2"}
    assert tail[5][1] == "Кабель 3x2"


def test_parse_table_flags_bracket_number():
    table = [
        ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"],
        ["1", "Раздел", "", ""],
        ["18)", "Монтаж", "шт", "2"],
    ]
    parsed = parse_table(table)
    idx = parsed.headers.index("№ п/п")
    assert [r[idx] for r in parsed.rows][-1] == "18)"
    assert parsed.number_issues == ["18)"]


def test_number_moves_from_name_to_position_column():
    table = [
        ["Поз.", "Наименование и техническая характеристика", "Кол-во"],
        ["1", "2", "3"],
        ["", "1. 2. Прибор", "1"],
        ["", "1. 3. Кабель", "3"],
        ["", "1. 4 Разъем", "4"],
        ["", "2.", "5"],
        ["", "2. 1. Шина", "6"],
        ["", "100 шт", "7"],
        ["2.2", "Уже есть", "8"],
    ]
    rows = parse_table(table).rows
    assert [(r[0], r[1]) for r in rows] == [
        ("1.2", "Прибор"),
        ("1.3", "Кабель"),
        ("1.4", "Разъем"),
        ("2", ""),
        ("2.1", "Шина"),
        ("", "100 шт"),
        ("2.2", "Уже есть"),
    ]


def test_numbers_not_moved_below_threshold():
    table = [
        ["Поз.", "Наименование", "Кол-во"],
        ["1", "2", "3"],
        ["", "1. Прибор", "1"],
        ["", "Оборудование", ""],
        ["", "Кабели", ""],
        ["", "2. Кабель", "3"],
    ]
    rows = parse_table(table).rows
    assert [(r[0], r[1]) for r in rows] == [
        ("", "1. Прибор"), ("", "Оборудование"), ("", "Кабели"), ("", "2. Кабель")]


def test_numbers_moved_with_some_unnumbered_rows():
    table = [
        ["Поз.", "Наименование", "Кол-во"],
        ["1", "2", "3"],
        ["", "1. Прибор", "1"],
        ["", "2. Кабель", "3"],
        ["", "3. Шина", "3"],
        ["", "4. Шкаф", "3"],
        ["", "Раздел", ""],
    ]
    rows = parse_table(table).rows
    assert [r[0] for r in rows] == ["1", "2", "3", "4", ""]


def test_wrapped_name_merged_by_sequence():
    table = [
        ["№ п/п", "Наименование", "Ед. изм.", "Кол-во"],
        ["1", "2", "3", "4"],
        ["2.36", "Труба", "м", "5"],
        ["2.37", "Труба с", "м", "6"],
        ["", "воздуховодами", "", ""],
        ["2.38", "Хомут", "шт", "7"],
        ["3.", "Кабельная продукция", "", ""],
        ["3.1", "Кабель", "м", "1"],
    ]
    rows = parse_table(table).rows
    assert [(r[0], r[1]) for r in rows] == [
        ("2.36", "Труба"),
        ("2.37", "Труба с воздуховодами"),
        ("2.38", "Хомут"),
        ("3.", "Кабельная продукция"),
        ("3.1", "Кабель"),
    ]


def test_wrap_before_section_merged():
    table = [
        ["№ п/п", "Наименование", "Ед. изм.", "Кол-во"],
        ["1", "2", "3", "4"],
        ["2.44", "Труба", "м", "5"],
        ["2.45", "Труба с", "м", "6"],
        ["", "воздуховодами", "", ""],
        ["3", "Кабельная продукция", "", ""],
        ["3.1", "Кабель", "м", "1"],
    ]
    names = [r[1] for r in parse_table(table).rows]
    assert names == ["Труба", "Труба с воздуховодами", "Кабельная продукция", "Кабель"]


def test_text_in_position_column_with_name_number_is_flagged():
    table = [
        ["Поз.", "Наименование", "Кол-во"],
        ["1", "2", "3"],
        ["УПСД ЭЭ (ЕДЦМ)", "1. Шкаф", "1"],
        ["", "1.1 Шина", "2"],
    ]
    parsed = parse_table(table)
    assert [(r[0], r[1]) for r in parsed.rows] == [("УПСД ЭЭ (ЕДЦМ)", "1. Шкаф"), ("1.1", "Шина")]
    assert parsed.number_issues == ["УПСД ЭЭ (ЕДЦМ)"]


def test_kit_info_reports_number_issues_but_check_ignores_them():
    row = {
        "id": 1,
        "path": "ЕСТ-ПМ-80825-Р-1-АГПП/ИЗМ0/a.docx",
        "doc_code": "ЕСТ-ПМ-80825-Р-1-АГПП.ВОР",
        "revision": 0,
        "meta_json": '{"number_issues": ["18)"]}',
    }
    info = kits.kit_info(row)
    assert "18)" in info["kit_problem"]
    assert kits.check_kits([row]) == []




def test_repeated_number_all_in_names_column_empty():
    rows = [['1', '2', '3']]
    rows.append(['', '14. Раздел', ''])
    for _ in range(4):
        rows.append(['', '14.1 Кабель 1x2', 'м'])
    rows.append(['', '14.2 Коробка', 'шт'])
    rows.append(['', '14.3 Лента', 'шт'])
    t = [['Поз.', 'Наименование', 'Ед. изм.']] + rows
    parsed = parse_table(t)
    nums = [r[0] for r in parsed.rows if r[1].startswith('Кабель')]
    assert nums == ['14.1'] * 4
