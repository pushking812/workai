import zipfile
from pathlib import Path

import pytest

from core import svor

ROOT = Path(__file__).resolve().parent.parent


def test_status_by_numbers():
    assert svor.status_by_numbers(0, 5) == "новая"
    assert svor.status_by_numbers(None, 5) == "новая"
    assert svor.status_by_numbers(5, 0) == "удалена"
    assert svor.status_by_numbers(5, 3) == "изменена"
    assert svor.status_by_numbers(5, 5) == "без изменений"
    assert svor.status_by_numbers(None, None) == ""


def test_color_of_runs():
    assert svor.color_of_runs(["000000", None, "auto"]) == ""
    assert svor.color_of_runs(["FF0000", "000000"]) == "красный"
    assert svor.color_of_runs(["00B050"]) == "зелёный"
    assert svor.color_of_runs(["hl:cyan"]) == "подсветка"
    assert svor.color_of_runs(["FF0000", "00B050"]) == "смешанный"


def _row(p, r, dev, color=""):
    return {"П": p, "Р": r, "Откл": dev, "Цвет": color}


def test_classify_notes():
    rows = svor.classify([_row(0, 5, 5, "зелёный"), _row(5, 3, -2), _row(5, 3, 0, "зелёный"),
                          _row(0, 5, 5, "красный"), _row(0, 5, 5, "")])
    assert [r["Статус"] for r in rows] == ["новая", "изменена", "изменена", "новая", "новая"]
    assert rows[0]["Замечание"] == ""
    assert rows[1]["Замечание"] == ""
    assert "зелёный, но по числам не новая" in rows[2]["Замечание"]
    assert "отклонение не равно Р-П" in rows[2]["Замечание"]
    # красный у новой (Изм.2) и отсутствие цвета замечаний не дают
    assert rows[3]["Замечание"] == "" and rows[4]["Замечание"] == ""


def _docx(path, rows):
    """Минимальный docx: одна таблица, строки - списки (текст, цвет или None) на 7 ячеек."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    trs = ""
    for row in rows:
        tcs = ""
        for text, color in row:
            rpr = '<w:rPr><w:color w:val="%s"/></w:rPr>' % color if color else ""
            tcs += "<w:tc><w:p><w:r>%s<w:t>%s</w:t></w:r></w:p></w:tc>" % (rpr, text)
        trs += "<w:tr>%s</w:tr>" % tcs
    xml = '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body><w:tbl>%s</w:tbl></w:body></w:document>' % (ns, trs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_read_row_colors_by_key(tmp_path):
    f = tmp_path / "s.docx"
    _docx(f, [[("1", None), ("Укладка труб d=110", "FF0000"), ("м", "FF0000"), ("690", "FF0000"), ("790", "FF0000"),
               ("100", "FF0000"), ("", None)],
              [("2", None), ("Монтаж шкафа", None), ("шт.", None), ("1", None), ("1", None), ("0", None), ("", None)],
              [("3", None), ("Монтаж шкафа", "00B050"), ("шт.", None), ("0", None), ("1", None), ("1", None), ("", None)]])
    colors = svor.read_row_colors(str(f))
    assert colors[svor._key("Укладка труб d=110", 690.0, 790.0)] == ["красный"]
    assert colors[svor._key("Монтаж шкафа", 1.0, 1.0)] == [""]
    assert colors[svor._key("Монтаж шкафа", 0.0, 1.0)] == ["зелёный"]


def _real(pattern_dir, name_part):
    base = ROOT / "РД" / pattern_dir
    hits = [p for p in base.rglob("*.docx") if name_part in p.name] if base.exists() else []
    return hits[0] if hits else None


def test_real_es1_izm2_colors():
    p = _real("ЕСТ-ПМ-80825-Р-1-ЭС1/ИЗМ2 - согласован", "СВОР")
    if not p:
        pytest.skip("нет СВОР ЭС1 Изм.2")
    rows = svor.read_svor(str(p))
    green = [r for r in rows if r["Цвет"] == "зелёный"]
    red = [r for r in rows if r["Цвет"] == "красный"]
    assert len(green) >= 25 and len(red) >= 8
    # все зелёные строки по числам новые, кроме явных ошибок отклонения
    assert sum(1 for r in green if r["Статус"] == "новая") >= len(green) - 1


def test_real_ksob_two_colors():
    p = _real("ЕСТ-ПМ-80825-Р-1-КСОБ/ИЗМ1 - согласован", "СВОР")
    if not p:
        pytest.skip("нет СВОР КСОБ")
    rows = svor.read_svor(str(p))
    red = [r for r in rows if r["Цвет"] == "красный"]
    green = [r for r in rows if r["Цвет"] == "зелёный"]
    assert len(red) >= 30 and len(green) >= 25
    assert sum(1 for r in red if r["Статус"] == "удалена") >= len(red) * 0.9
