"""Профили шапок кабельного журнала и очистка колонок (Этап 1, п. 9)."""

from __future__ import annotations

import pytest

from core.parsers.header_profiles import (
    PROFILE_CABLE_BASIC,
    PROFILE_CABLE_PIPES,
    PROFILE_CABLE_SECTION,
    PROFILE_GENERIC,
    PROFILE_UNKNOWN,
    detect_header_profile,
    parse_table,
)
from core.transformer.schema_analyzer import normalize_header


# --- normalize_header ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("№ п/п", "NПП"),
        ("Ед. изм.", "ЕдИзм"),
        ("Наименование работ", "НаименованиеРабот"),
        ("Кол., число и сечение жил", "КолЧислоИСечЖил"),
        ("Кол, число и сечение жил", "КолЧислоИСечЖил"),
        ("по проекту", "ПоПроекту"),
        ("ПО ПРОЕКТУ", "ПоПроекту"),
        ("Ёлка", "Елка"),
        ("Длина м", "ДлинаМ"),
        ("Длина, м", "ДлинаМ"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_header(raw, expected):
    assert normalize_header(raw) == expected


def test_normalize_header_truncates_words_from_third():
    # Итог длиннее 15 символов -> слова с третьего усекаются до 3 символов.
    assert normalize_header("Формула расчета, расчет объемов работ") == "ФормулаРасчетаРасОбъРаб"
    # Первые два слова не меняются, даже если они длинные.
    assert normalize_header("Электрооборудование щитов") == "ЭлектрооборудованиеЩитов"
    # Итог не длиннее 15 символов -> без усечения.
    assert normalize_header("Наименование") == "Наименование"
    assert normalize_header("Ед изм работ") == "ЕдИзмРабот"


# --- профили ---------------------------------------------------------------

BASIC_HEADER = [
    ["Обозначение кабеля, провода", "Трасса", "Трасса", "Кабель, провод", "Кабель, провод", "Кабель, провод",
     "Кабель, провод", "Кабель, провод", "Кабель, провод"],
    ["Обозначение кабеля, провода", "Начало", "Конец", "По проекту", "По проекту", "По проекту",
     "Проложен", "Проложен", "Проложен"],
    ["Обозначение кабеля, провода", "Начало", "Конец", "Марка", "Кол, число и сечение жил", "Длина, м",
     "Марка", "Кол, число и сечение жил", "Длина, м", "Длина, м"],  # лишняя 10-я ячейка только в нижней строке
]

BASIC_COLUMNS = [
    "ОбозначениеКабеляПро",
    "Трасса|Начало",
    "Трасса|Конец",
    "КабельПровод|ПоПроекту|Марка",
    "КабельПровод|ПоПроекту|КолЧислоИСечЖил",
    "КабельПровод|ПоПроекту|ДлинаМ",
]


def test_cable_basic_drops_empty_fact_block_and_stray_column():
    table = BASIC_HEADER + [
        ["1", "А", "Б", "КПС", "5х1", "8", "", "", "", ""],
        ["2", "В", "Г", "КПС", "", "9", "", "", "", ""],
    ]
    parsed = parse_table(table)
    assert parsed.profile == PROFILE_CABLE_BASIC
    assert parsed.headers == BASIC_COLUMNS
    assert parsed.rows == [["1", "А", "Б", "КПС", "5х1", "8"], ["2", "В", "Г", "КПС", "", "9"]]
    assert len(parsed.dropped) == 4


def test_cable_basic_drops_fact_block_even_with_data():
    """Блок «Проложен» не используется и не выгружается, даже если заполнен."""
    table = BASIC_HEADER + [
        ["1", "А", "Б", "КПС", "5х1", "8", "КПС", "5х1", "", ""],
    ]
    parsed = parse_table(table)
    assert parsed.headers == BASIC_COLUMNS
    assert parsed.rows == [["1", "А", "Б", "КПС", "5х1", "8"]]
    assert len(parsed.dropped) == 4


def test_section_rows_do_not_count_as_fact_data():
    """Строка-раздел с текстом во всех колонках не делает заготовку «непустой»."""
    section = ["Линии связи"] * 10
    table = BASIC_HEADER + [section, ["1", "А", "Б", "КПС", "5х1", "8", "", "", "", ""]]
    parsed = parse_table(table)
    assert parsed.headers == BASIC_COLUMNS
    assert parsed.rows[0] == ["Линии связи"] * 6  # строка раздела сохраняется для Power Query


def test_empty_data_rows_are_removed():
    table = BASIC_HEADER + [[""] * 10, ["1", "А", "Б", "КПС", "5х1", "8", "", "", "", ""]]
    assert len(parse_table(table).rows) == 1


SECTION_HEADER = [
    ["Обозначение кабеля, провода", "Трасса", "Трасса", "Участок трассы кабеля", "по проекту", "по проекту",
     "по проекту", "Участок трассы кабеля", "проложен", "проложен", "проложен"],
    ["Обозначение кабеля, провода", "Начало", "Конец", "Участок трассы кабеля", "Марка", "Кол., число и сечение жил",
     "Длина, м", "Участок трассы кабеля", "Марка", "Кол., число и сечение жил", "Длина, м"],
    [str(number) for number in range(1, 12)],
]


def test_cable_section_columns_8_to_11_are_always_skipped():
    table = SECTION_HEADER + [
        ["1", "А", "Б", "уч. 1", "КПС", "5х1", "8", "уч. 2", "КПС", "", ""],
    ]
    parsed = parse_table(table)
    assert parsed.profile == PROFILE_CABLE_SECTION
    assert parsed.headers == [
        "ОбозначениеКабеляПро",
        "Трасса|Начало",
        "Трасса|Конец",
        "УчастокТрассыКаб",
        "ПоПроекту|Марка",
        "ПоПроекту|КолЧислоИСечЖил",
        "ПоПроекту|ДлинаМ",
    ]
    assert parsed.rows == [["1", "А", "Б", "уч. 1", "КПС", "5х1", "8"]]
    assert len(parsed.dropped) == 4


def test_cable_pipes_profile_and_empty_separator_column():
    table = [
        ["Обозначение кабеля, провода", "Трасса", "Трасса", "Проход через", "Кабель, провод", "", "Бирка", "Бирка"],
        ["Обозначение кабеля, провода", "Начало", "Конец", "Труба", "Проложен", "", "№ бирки", "Сторона"],
        ["Обозначение кабеля, провода", "Начало", "Конец", "Обозначение", "Марка", "", "№ бирки", "Лицевая"],
        ["1", "А", "Б", "Т1", "", "", "7", "8004"],
    ]
    parsed = parse_table(table)
    assert parsed.profile == PROFILE_CABLE_PIPES
    assert parsed.headers == [
        "ОбозначениеКабеляПро",
        "Трасса|Начало",
        "Трасса|Конец",
        "ПроходЧерез|Труба|Обозначение",
        "Бирка|NБирки",
        "Бирка|Сторона|Лицевая",
    ]
    assert parsed.rows == [["1", "А", "Б", "Т1", "7", "8004"]]
    assert len(parsed.dropped) == 2


def test_flat_table_is_generic_and_untouched():
    table = [["№ п/п", "Наименование", "Ед."], ["1", "Кабель", "м"], ["", "", ""]]
    parsed = parse_table(table)
    assert parsed.profile == PROFILE_GENERIC
    assert parsed.headers == ["№ п/п", "Наименование", "Ед."]
    assert parsed.rows == [["1", "Кабель", "м"], ["", "", ""]]
    assert not parsed.dropped


def test_hierarchical_but_not_cable_journal_is_unknown():
    assert detect_header_profile(["Система", "Кол|1", "Кол|2"], True) == PROFILE_UNKNOWN
    assert detect_header_profile(["Система"], False) == PROFILE_GENERIC
