"""reconcile_totals.py: пустой лист Связь_ВОР_СО (только заголовок или 1x1) считается отсутствующим."""
import subprocess
import sys
from pathlib import Path

import openpyxl

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "reconcile_totals.py"


def _book(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)


def test_empty_link_sheet_falls_back_to_pivot(tmp_path):
    _check(tmp_path, [[None]])


def test_truncated_link_sheet_falls_back_to_pivot(tmp_path):
    """Лист связи с урезанным набором столбцов (8 из 34) не используется."""
    _check(tmp_path, [["Шифр", "NПП", "КолВо", "ЕдИзм", "НаименованиеРабот", "Раздел", "ДатаИзм", "НомИзм"],
                      ["x", 1, 5, "шт", "Кабель", "r", None, 0]])


def _check(tmp_path, link_rows):
    vor_head = [["НаименованиеРабот", "КолВо", "ЕдИзм"]]
    so_head = [["НаименованиеИТехХар", "КолВо", "ЕдИзм"]]
    _book(tmp_path / "v.xlsx", {"ФайлBinary": vor_head})
    _book(tmp_path / "s.xlsx", {"ФайлBinary": so_head})
    _book(tmp_path / "c.xlsx", {
        "Связь_ВОР_СО": link_rows,
        "Сводная": [["Названия строк", "СуммаВОР", "СуммаСО", "СтатусСвязи"],
                    ["Кабель", None, None, None],
                    ["Кабель КСВВ", 10, 10, "точно"],
                    ["Общий итог", 10, 10, None]],
        "Только_в_ВОР": [["НаименованиеРабот", "КолВо", "ЕдИзм"]],
        "Только_в_СО": [["НаименованиеИТехХар", "КолВо", "ЕдИзм"]],
    })
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", str(SCRIPT), str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8")
    assert "IndexError" not in p.stderr, p.stderr[-500:]
    assert "нет листа Связь_ВОР_СО" in p.stdout, p.stdout + p.stderr[-500:]
