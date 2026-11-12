from core.parsers.stamp_parser import newest_filename_date


def test_newest_filename_date_full():
    assert newest_filename_date("ВОР Изм.1 от 2025.08.15.docx") == "2025-08-15"


def test_newest_filename_date_month_only_is_first_day():
    assert newest_filename_date("ВОР 2026.04.docx") == "2026-04-01"


def test_newest_filename_date_none():
    assert newest_filename_date("ВОР.docx") is None


def test_newest_filename_date_takes_last():
    assert newest_filename_date("ВОР 2025.08.15 и 17.06.26.docx") == "2026-06-17"
