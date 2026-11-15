"""СВОР: сводка по статусам и цветам; замечания, где цвет не подходит к числам.

Запуск (из venv):  python -I -X utf8 scripts/svor_report.py <СВОР.docx> [<СВОР.docx> ...] [--rows]
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.svor import read_row_colors, read_svor  # noqa: E402


def main(paths, show_rows=False):
    for p in paths:
        try:
            rows = read_svor(p)
        except Exception as e:  # noqa: BLE001 - отчёт по пачке файлов не должен падать на одном
            print(Path(p).name[:50], "ОШИБКА", type(e).__name__, str(e)[:80])
            continue
        st = collections.Counter(r["Статус"] for r in rows)
        col = collections.Counter(r["Цвет"] or "-" for r in rows)
        xml_colored = sum(1 for v in read_row_colors(p).values() for c in v if c)
        got = sum(1 for r in rows if r["Цвет"])
        notes = [r for r in rows if r["Замечание"]]
        print(f"{Path(p).name[:50]}: строк {len(rows)}, статусы {dict(st)}, цвет {dict(col)}, "
              f"цветных в XML {xml_colored}, сопоставлено {got}, замечаний {len(notes)}")
        if show_rows:
            for r in notes[:10]:
                print("    ", r["Номер"], r["Наименование"][:40], r["П"], r["Р"], r["Откл"], r["Цвет"], "|", r["Замечание"])


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("--")], "--rows" in sys.argv)
