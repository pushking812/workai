from pathlib import Path

Q = Path(__file__).resolve().parent.parent / "PQ" / "СО" / "запросы" / "ФайлBinary.pq"


def test_collapse_key_has_section_label():
    text = Q.read_text(encoding="utf-8-sig")
    assert "_МеткаПрим" in text
    assert "наземн" in text and "подземн" in text
    assert 'Table.RemoveColumns(Table.Combine' in text
