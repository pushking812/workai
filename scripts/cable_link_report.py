"""Связь КЖ и СО по марке и сечению: сводка и таблица пар.

Запуск (из venv):  python -I -X utf8 scripts/cable_link_report.py <КЖ.docx> <СО.docx> [--rows]
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import cable_link  # noqa: E402
from core.cable_docs import read_kzh, read_so  # noqa: E402


def main(kzh_path, so_path, show_rows=False):
    kzh, so = read_kzh(kzh_path), read_so(so_path)
    res = cable_link.link(kzh, so)
    cnt = collections.Counter(r["Статус"] for r in res)
    print(f"КЖ строк {len(kzh)}, СО строк {len(so)}, групп {len(res)}: {dict(cnt)}")
    if show_rows:
        for r in res:
            print("  ", r["Статус"], r["Режим"], r["МаркаКЖ"][:30], r["Сечение"], r["КЖ_м"], r["СО_м"], r["КлючСО"][:40])
    return res


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--rows" in sys.argv)
