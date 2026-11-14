"""Поиск строк ВОР, где позиция спецификации указана в наименовании работ, а не в колонке со ссылкой.

Для каждого docx/doc ВОР в РД/ читает таблицы, находит колонки «Наименование» и «ссылка на
спецификацию/чертёж» и печатает строки, где в наименовании есть «поз.» (или «п.» с номером).
Пишет tsv: файл, номер, ссылка, найденные в наименовании позиции, наименование.

Запуск (из venv):  python -I -X utf8 scripts/find_spec_in_name.py [РД] [data/converted] [отчёт.tsv]
"""
import re
import sys
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from find_dup_cases import is_vor, norm, resolve  # noqa: E402

# «поз. 5», «поз.5,6», «поз. 5-8», «(позиции 5, 6)»
POS_RE = re.compile(r"поз(?:иц\w*|\.)?\s*№?\s*([0-9][0-9.,\s\-–и]*)", re.I)


def vor_rows(path):
    with numbering_fixed(str(path)) as fixed:
        d = docx.Document(fixed)
    out, hdr = [], None
    for tb in d.tables:
        rows = []
        for r in tb.rows:
            try:
                rows.append([c.text.strip() for c in r.cells])
            except Exception:
                rows.append([])
        for i, cells in enumerate(rows[:6]):
            h = [norm(c) for c in cells]
            if any("№" in x for x in h) and any("наименование" in x for x in h):
                hdr = (len(h),
                       next(j for j, x in enumerate(h) if "№" in x),
                       next(j for j, x in enumerate(h) if "наименование" in x),
                       [j for j, x in enumerate(h) if "специф" in x or "ссылка" in x])
                rows = rows[i + 1:]
                break
        if hdr is None:
            continue
        for cells in rows:
            if len(cells) != hdr[0]:
                continue
            ref = " ".join(cells[j] for j in hdr[3])
            out.append((cells[hdr[1]].rstrip("."), cells[hdr[2]], ref))
    return out


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "РД")
    conv = Path(sys.argv[2] if len(sys.argv) > 2 else "data/converted")
    rep = Path(sys.argv[3] if len(sys.argv) > 3 else "data/exports/_report_spec_in_name.tsv")
    lines = ["файл\tномер\tссылка\tпозиции в наименовании\tнаименование"]
    total = 0
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in (".doc", ".docx") or p.name.startswith("~$") or not is_vor(p.name):
            continue
        dp = resolve(p, conv)
        if dp is None:
            print("нет docx:", p.name)
            continue
        try:
            rows = vor_rows(dp)
        except Exception as e:  # noqa: BLE001
            print("ошибка:", p.name, e)
            continue
        hit = 0
        for num, name, ref in rows:
            m = POS_RE.findall(name)
            if m:
                hit += 1
                lines.append("\t".join([str(p.relative_to(root)), num, ref.replace("\n", " "),
                                         "; ".join(x.strip() for x in m), name.replace("\n", " ")]))
        total += hit
        print(f"{hit:3d} из {len(rows):4d}  {p.relative_to(root)}")
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("\n".join(lines), encoding="utf-8")
    print("всего", total, "->", rep)


if __name__ == "__main__":
    main()
