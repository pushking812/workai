from core.parsers.docx_parser import extract_headers
from core.parsers.header_profiles import parse_table


def test_continuation_table_has_no_header():
    table = [
        ["18)", "", "Гидравлические испытания", "м", "7"],
        ["", "", "Спринклерная секция .", "", ""],
        ["19)", "", "Установка . Распылитель", "Шт.", "41"],
    ]
    headers, start = extract_headers(table)
    assert not any(headers)
    assert start == 0
    assert len(parse_table(table).rows) == 3


def test_paren_numbering_ends_header():
    table = [
        ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"],
        ["", "Разбивка трассы", "", ""],
        ["1)", "Разбивка трассы направлением", "м", "46"],
    ]
    headers, start = extract_headers(table)
    assert headers == ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"]
    assert start == 1
