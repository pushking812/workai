import os

import pytest

from core.parsers.docx_parser import extract_tables_from_docx
from core.parsers.numbering_fix import numbering_fixed

APT = os.path.join("ВОР", "ЕСТ-ПМ-80825-Р-1-АПТ.ВОР 1.02.2023.docx")


def _first_cells(path):
    return [
        [row[0] if row else "" for row in table]
        for table in extract_tables_from_docx(path)
    ]


@pytest.mark.skipif(not os.path.exists(APT), reason="нет эталонного файла АПТ")
def test_apt_numbers_match_word():
    before = os.path.getsize(APT)
    with numbering_fixed(APT) as fixed:
        assert fixed != APT
        tables = _first_cells(fixed)
    flat = [str(c).strip() for t in tables for c in t]
    # номера, подтверждённые в самом документе Word
    for expected in ("18", "41.1", "41.2", "82.3"):
        assert any(c.startswith(expected) for c in flat), expected
    assert not any(c.startswith(("18)", "2)")) for c in flat)
    assert os.path.getsize(APT) == before


def test_file_without_numbering_returns_source(tmp_path):
    from docx import Document

    path = tmp_path / "plain.docx"
    Document().save(str(path))
    with numbering_fixed(str(path)) as fixed:
        assert fixed == str(path)


def test_non_docx_returned_as_is(tmp_path):
    path = tmp_path / "a.doc"
    path.write_bytes(b"x")
    with numbering_fixed(str(path)) as fixed:
        assert fixed == str(path)
