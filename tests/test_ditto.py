"""`- // -` в ячейке заменяется значением из предыдущей строки."""
from core.parsers.header_profiles import expand_ditto, is_ditto

HEADERS = ["NПП", "Наименование", "Тип", "Код", "Завод", "Ед", "Кол-во"]


def test_is_ditto_variants():
    for value in ["- // -", "-//-", " - // - ", "–//–", '- " -', "〃"]:
        assert is_ditto(value), value
    for value in ["", "-", "Россия", "//", "ГОСТ - 1"]:
        assert not is_ditto(value), value


def test_ditto_replaced_with_previous_value_and_chain():
    rows = [
        ["5.1", "Труба", "42х3", "ГОСТ 8732-78", "Россия", "м", "6"],
        ["5.2", "Труба", "34х3", "- // -", "- // -", "м", "21"],
        ["5.3", "Труба", "27х3", "- // -", "- // -", "м", "9"],
    ]
    out = expand_ditto(HEADERS, rows)
    assert [r[3] for r in out] == ["ГОСТ 8732-78"] * 3
    assert [r[4] for r in out] == ["Россия"] * 3


def test_ditto_skips_blank_and_section_rows():
    rows = [
        ["1.1", "Шкаф", "", "", "Tellabs", "шт.", "1"],
        ["", "", "", "", "", "", ""],
        ["2", "Раздел", "", "", "", "", ""],
        ["2.1", "Стойка", "", "", "- // -", "шт.", "1"],
    ]
    assert expand_ditto(HEADERS, rows)[3][4] == "Tellabs"


def test_ditto_without_previous_value_is_kept():
    rows = [
        ["1", "Шкаф", "", "", "- // -", "шт.", "1"],
        ["2", "Стойка", "", "", "- // -", "шт.", "1"],
    ]
    out = expand_ditto(HEADERS, rows)
    assert out[0][4] == "- // -" and out[1][4] == "- // -"


def test_ditto_number_column_untouched():
    rows = [["1", "А", "", "", "", "шт.", "1"], ["- // -", "Б", "", "", "", "шт.", "1"]]
    assert expand_ditto(HEADERS, rows)[1][0] == "- // -"


def test_ditto_takes_first_non_empty_above_when_previous_is_empty():
    rows = [
        ['30', 'Громкоговоритель', 'А', '', 'НПП Мета', 'шт.', '2'],
        ['31', 'Громкоговоритель 2', '', '', '', 'шт.', '1'],
        ['32', 'Громкоговоритель 3', 'Б', '', '- // -', 'шт.', '1'],
    ]
    assert expand_ditto(HEADERS, rows)[2][4] == 'НПП Мета'

