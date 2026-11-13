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


def _svor_es2():
    folder = "СВОР"
    if not os.path.isdir(folder):
        return None
    for name in os.listdir(folder):
        if name.startswith("28_") and "ЭС2.СВОР" in name and name.endswith(".docx"):
            return os.path.join(folder, name)
    return None


@pytest.mark.skipif(_svor_es2() is None, reason="нет файла СВОР ЭС2")
def test_style_numbering_is_materialised():
    """Нумерация задана стилем абзаца (pStyle -> styles.xml), а не прямым numPr."""
    path = _svor_es2()
    with numbering_fixed(path) as fixed:
        assert fixed != path
        flat = [c for t in _first_cells(fixed) for c in t]
    numbers = [int(c) for c in flat if c.isdigit()]
    assert 54 in numbers and 30 in numbers


def test_style_numbering_unit():
    from scripts.docx_fix_numbering import parse_style_numbering

    styles = (
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:styleId="A"><w:pPr><w:numPr><w:numId w:val="5"/></w:numPr></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="B"><w:basedOn w:val="A"/>'
        '<w:pPr><w:numPr><w:ilvl w:val="1"/></w:numPr></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="C"/></w:styles>'
    ).encode()
    result = parse_style_numbering(styles)
    assert result["A"] == ("5", None)
    assert result["B"] == ("5", "1")
    assert "C" not in result


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


IZM1 = os.path.join(
    "РД", "ЕСТ-ПМ-80825-Р-1-АПС", "ИЗМ1 - согласован", "Ред. формат",
    "21. ВОР_Изм.1 от 2025.10._(Нов.)_Изм.1 - 2026-09-17.docx",
)


@pytest.mark.skipif(not os.path.exists(IZM1), reason="нет файла 21. ВОР Изм.1")
def test_hidden_numbered_paragraphs_are_not_written():
    """Скрытые (vanish) абзацы с номером считаются, но в ячейку не попадают."""
    with numbering_fixed(IZM1) as fixed:
        flat = [str(c).strip() for t in _first_cells(fixed) for c in t]
    assert "31.1" in flat
    assert not any(c.startswith("1 2 3") for c in flat)
