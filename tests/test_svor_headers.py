"""СВОР: шифр документа из `Кол-во (стадия П/Р) <шифр>` уходит в метаданные файла."""

import json

from core import database
from core.parsers.header_profiles import parse_table, split_stage_header

CODE_P = "ЕСТ-ПМ-80825-1-ИОС2.2.ВОР"
CODE_R = "ЕСТ-ПМ-80825-Р-1-ИОС2.2.ВОР (вер. 1)"

SVOR_TABLE = [
    [
        "№ п/п",
        "Наименование работ",
        "Ед. изм.",
        "Кол-во (стадия П) " + CODE_P,
        "Кол-во (стадия Р) " + CODE_R,
        "Разница Р-П",
        "Примечание",
    ],
    ["1", "Монтаж кабеля", "м", "10", "12", "2", ""],
]


def test_split_stage_header_cuts_code_and_keeps_stage():
    assert split_stage_header("Кол-во (стадия П) " + CODE_P) == ("Кол-во (стадия П)", "П", CODE_P)
    assert split_stage_header("Кол-во (стадия Р) " + CODE_R) == ("Кол-во (стадия Р)", "Р", CODE_R)


def test_split_stage_header_variants():
    assert split_stage_header("Кол-во (стадия Р изм.1) ЕСТ-Р-1-СКК") == (
        "Кол-во (стадия Р)",
        "Р",
        "ЕСТ-Р-1-СКК (изм.1)",
    )
    assert split_stage_header("Кол-во По РД (изм. 2) ЕСТ-Р-1-ЭО1.ВОР") == (
        "Кол-во (стадия Р)",
        "Р",
        "ЕСТ-Р-1-ЭО1.ВОР (изм. 2)",
    )


def test_split_stage_header_ignores_other_headers():
    assert split_stage_header("Ед. изм.") == ("Ед. изм.", "", "")
    assert split_stage_header("Кол-во") == ("Кол-во", "", "")


def test_parse_table_strips_code_from_headers_and_collects_codes():
    parsed = parse_table(SVOR_TABLE)
    assert parsed.headers[3] == "Кол-во (стадия П)"
    assert parsed.headers[4] == "Кол-во (стадия Р)"
    assert parsed.stage_codes == {"П": CODE_P, "Р": CODE_R}
    assert len(parsed.rows) == 1


def test_same_schema_for_different_codes():
    other = [list(row) for row in SVOR_TABLE]
    other[0][3] = "Кол-во (стадия П) ДРУГОЙ-ШИФР"
    assert parse_table(other).headers == parse_table(SVOR_TABLE).headers


def test_empty_trailing_column_is_dropped():
    table = [row + [""] for row in SVOR_TABLE]
    parsed = parse_table(table)
    assert parsed.headers == parse_table(SVOR_TABLE).headers
    assert all(len(row) == len(parsed.headers) for row in parsed.rows)
    assert parsed.dropped


def test_unnamed_column_duplicating_neighbour_is_dropped():
    table = [list(row) for row in SVOR_TABLE]
    table.append(["2", "Прокладка", "м", "5", "5", "0", "Текст", "Текст"])
    parsed = parse_table(table)
    assert len(parsed.headers) == 7
    assert all(len(row) == 7 for row in parsed.rows)


def test_update_file_meta_merges_json(tmp_path):
    connection = database.init_db(str(tmp_path / "t.db"))
    database.add_file(connection, "h1", "a.docx", "a.docx")
    database.update_file_meta(connection, "h1", {"stage_codes": {"П": CODE_P}})
    database.update_file_meta(connection, "h1", {"other": 1})
    row = connection.execute("SELECT meta_json FROM files WHERE hash = 'h1'").fetchone()
    assert json.loads(row["meta_json"]) == {"stage_codes": {"П": CODE_P}, "other": 1}
    connection.close()
