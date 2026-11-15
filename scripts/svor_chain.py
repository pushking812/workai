"""Проверка цепочки изменений СВОР по всем изменениям шифра. Листы: СВОР_Цепочка, Ошибки.

Запуск (из venv):  python -I -X utf8 scripts/svor_chain.py [корень=РД] [выход.xlsx] [--cipher ЭС1]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

from core.svor_chain import run  # noqa: E402

ERR_COLS = ["Шифр", "Изм", "Раздел", "Наименование", "Код", "Описание"]


def build(root, out, only=None):
    result = {k: v for k, v in run(root).items() if not only or only in k}
    wb = Workbook()
    ws, we = wb.active, wb.create_sheet("Ошибки")
    ws.title = "СВОР_Цепочка"
    cols = []
    for chain, _ in result.values():
        for rec in chain:
            for k in rec:
                if k not in cols:
                    cols.append(k)
    ws.append(cols)
    we.append(ERR_COLS)
    n_err = 0
    for chain, errs in result.values():
        for rec in chain:
            ws.append([rec.get(c) for c in cols])
        for e in errs:
            we.append([e.get(c) for c in ERR_COLS])
            n_err += 1
    wb.save(out)
    return {k: (len(v[0]), len(v[1])) for k, v in result.items()}, n_err


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = sys.argv[sys.argv.index("--cipher") + 1] if "--cipher" in sys.argv else None
    if only:
        args = [a for a in args if a != only]
    root = args[0] if args else str(ROOT / "РД")
    out = args[1] if len(args) > 1 else str(ROOT / "data" / "exports" / "СВОР_цепочка.xlsx")
    stat, n = build(root, out, only)
    for k, (a, b) in stat.items():
        if a or b:
            print(k, "позиций", a, "ошибок", b)
    print("ошибок всего", n, "->", out)
