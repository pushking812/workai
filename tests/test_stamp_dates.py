"""Дата выпуска: штамп → имя файла → дата последнего изменения файла."""

import os
import time

from core.parsers.stamp_parser import fallback_revision_date, parse_stamp


def test_fallback_date_from_filename(tmp_path):
    path = tmp_path / "ЕСТ-ПМ-80825-Р-1-ЭС1_ВОР от 17.06.26.docx"
    path.write_bytes(b"x")
    assert fallback_revision_date(str(path)) == ("2026-06-17", "filename")


def test_fallback_date_from_modified_time(tmp_path):
    path = tmp_path / "без даты.docx"
    path.write_bytes(b"x")
    moment = time.mktime((2024, 3, 5, 12, 0, 0, 0, 0, -1))
    os.utime(path, (moment, moment))
    assert fallback_revision_date(str(path)) == ("2024-03-05", "modified")


def test_fallback_date_missing_file():
    assert fallback_revision_date("нет_такого_файла.docx") == (None, "")


def test_parse_stamp_without_stamp_uses_modified_date(tmp_path):
    path = tmp_path / "пустой.docx"
    path.write_bytes(b"not a docx")
    moment = time.mktime((2023, 1, 9, 12, 0, 0, 0, 0, -1))
    os.utime(path, (moment, moment))
    result = parse_stamp(str(path))
    assert result["stamp_status"] == "MISSING"
    assert result["revision_date"] == "2023-01-09"
    assert result["revision_date_source"] == "modified"
