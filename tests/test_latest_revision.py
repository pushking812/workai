from core.parsers import stamp_parser as sp

LABELS = ["Изм.", "Кол.уч", "Лист", "№док", "Подп.", "Дата", "ЕСТ-ПМ-80825-Р-1-АПТ.ВОР", "Лист"]


def _row(*cells):
    return list(cells) + [""] * (10 - len(cells))


def _stamp(change_rows):
    rows = [
        _row("Разработал", "", "Иванов", "", "", "01.01.26"),
        _row("Проверил", "", "Петров", "", "", "01.01.26"),
    ]
    rows += change_rows
    rows.append(_row(*LABELS))
    return rows


def test_latest_revision_is_topmost_filled_row():
    rows = _stamp(
        [
            _row("3", "-", "Зам.", "120", "", "03.03.26"),
            _row("2", "-", "Зам.", "096", "", "02.02.26"),
            _row("1", "-", "Зам.", "035", "", "01.10.25"),
        ]
    )
    assert sp.latest_change_row(rows) == 2
    values = sp.read_stamp_values(rows)
    assert values[sp.LABEL_REVISION] == "3"
    assert sp.read_revision_date(rows) == "2026-03-03"


def test_partially_filled_changes_and_blank_rows():
    rows = _stamp(
        [
            _row("", "", "", "", "", ""),
            _row("2", "-", "Зам.", "096", "", "02.02.26"),
            _row("1", "-", "Нов.", "035", "", "01.10.25"),
        ]
    )
    assert sp.read_stamp_values(rows)[sp.LABEL_REVISION] == "2"


def test_roles_do_not_count_as_changes():
    rows = _stamp([_row("", "", "", "", "", "")])
    assert sp.latest_change_row(rows) == -1
    assert sp.read_stamp_values(rows)[sp.LABEL_REVISION] == "0"
