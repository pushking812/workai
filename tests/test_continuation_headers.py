from core.parsers.header_profiles import parse_table

HEAD = ["№ п/п", "№ в ЛСР", "Наименование работ", "Ед. изм.", "Кол-во"]


def test_headerless_continuation_keeps_first_table_columns():
    first = parse_table([HEAD, ["1", "2", "3", "4", "5"], ["1", "", "Труба", "м", "7"]])
    cont = parse_table([["18", "", "Кран", "шт", "3"], ["19", "", "Тройник", "шт", "4"]], like=first)
    assert cont.headers == first.headers
    assert cont.rows[0] == ["18", "", "Кран", "шт", "3"]


def test_headerless_continuation_with_extra_empty_cells():
    # Часть строк .doc приходит с лишней пустой ячейкой справа (10 вместо 5+1).
    first = parse_table([HEAD, ["1", "2", "3", "4", "5"], ["1", "", "Труба", "м", "7"]])
    cont = parse_table(
        [
            ["34", "", "Кабель", "м", "10", ""],
            ["35", "", "Кран", "шт", "3"],
            ["36", "", "Тройник", "шт", "4", ""],
        ],
        like=first,
    )
    assert cont.headers == first.headers
    assert [row[0] for row in cont.rows] == ["34", "35", "36"]
    assert all(len(row) == len(first.headers) for row in cont.rows)


def test_headerless_extra_nonempty_column_is_not_forced():
    first = parse_table([HEAD, ["1", "2", "3", "4", "5"], ["1", "", "Труба", "м", "7"]])
    cont = parse_table([["34", "", "Кабель", "м", "10", "лишнее"]], like=first)
    assert not any(cont.headers)


def test_headerless_other_width_is_not_forced():
    first = parse_table([HEAD, ["1", "2", "3", "4", "5"], ["1", "", "Труба", "м", "7"]])
    cont = parse_table([["18", "Кран", "шт"]], like=first)
    assert not any(cont.headers)
