"""Сдвинутые ссылки ВОР на позиции СО по всем комплектам из РД/.

Для строки ВОР с одной ссылкой «.СО (поз. X)» сравниваем её наименование с наименованием СО по позиции X
и по всем остальным позициям СО (слова по первым 5 знакам, числа обязаны быть в ВОР). Сдвиг: по X похожесть
низкая, а ровно одна другая позиция Y похожа сильно (и единица та же). Отчёт: data/exports/_report_ref_shift.tsv.

Запуск (из venv):  python -I -X utf8 scripts/analyze_ref_shift.py [РД] [data/converted] [подстрока пути]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze_volume_tolerance import read, unit  # noqa: E402
from find_dup_cases import is_so, is_vor, norm, resolve, tokens, vor_refs  # noqa: E402

LOW, HIGH = 0.34, 0.75


def stems(text):
    ws = {t[:5] for t in tokens(text) if not t[0].isdigit() and len(t) >= 3}
    return ws


def nums(text):
    return {t for t in tokens(text) if t[0].isdigit()}


def score(vname, so_rows):
    """Лучшая оценка по строкам СО одной позиции: доля слов СО, найденных в ВОР; числа СО должны быть в ВОР."""
    vs, vn = stems(vname), nums(vname)
    best = 0.0
    for r in so_rows:
        ss, sn = stems(r["name"]), nums(r["name"])
        if not ss:
            continue
        cov = len(ss & vs) / len(ss)
        if sn and not sn <= vn:
            cov *= 0.5
        best = max(best, cov)
    return best


def parts(n):
    p = n.split(".")
    return ".".join(p[:-1]), p[-1]


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "РД")
    conv = Path(sys.argv[2] if len(sys.argv) > 2 else "data/converted")
    flt = sys.argv[3] if len(sys.argv) > 3 else ""
    kits = defaultdict(lambda: ([], []))
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".doc", ".docx") or p.name.startswith("~$"):
            continue
        if "Обосновывающие" in str(p) or flt not in str(p):
            continue
        if is_vor(p.name):
            kits[p.parent][0].append(p)
        elif is_so(p.name):
            kits[p.parent][1].append(p)
    total = ok = weak = 0
    shifts = []
    per_kit = defaultdict(lambda: [0, 0, 0])
    for folder, (vors, sos) in kits.items():
        if not vors or not sos:
            continue
        so_data = {}
        for s in sos:
            sp = resolve(s, conv)
            if sp:
                try:
                    so_data[s] = read(sp, "so")
                except Exception as e:  # noqa: BLE001
                    print("ошибка СО", s.name, e)
        for v in vors:
            vp = resolve(v, conv)
            if not vp or not so_data:
                continue
            try:
                vrows = read(vp, "vor")
            except Exception as e:  # noqa: BLE001
                print("ошибка ВОР", v.name, e)
                continue
            refs = {x for r in vrows for x in vor_refs(r["ref"])}
            best, hits = None, 0
            for s, rows in so_data.items():
                h = len(refs & {r["num"] for r in rows})
                if h > hits:
                    best, hits = s, h
            if best is None:
                continue
            kit = str(folder.relative_to(root))
            by = defaultdict(list)
            for r in so_data[best]:
                by[r["num"]].append(r)
            print("комплект:", folder.name[:50], v.name[:30], flush=True)
            for r in vrows:
                rf = list(dict.fromkeys(vor_refs(r["ref"])))
                if len(rf) != 1 or rf[0] not in by:
                    continue
                x = rf[0]
                total += 1
                k = per_kit[kit]
                k[0] += 1
                sx = score(r["name"], by[x])
                if sx >= LOW:
                    ok += 1
                    continue
                weak += 1
                k[1] += 1
                cand = sorted(((score(r["name"], rows), n) for n, rows in by.items() if n != x
                               and any(unit(q["ed"]) == unit(r["ed"]) for q in rows)), reverse=True)
                if not cand or cand[0][0] < HIGH or (len(cand) > 1 and cand[1][0] >= cand[0][0] - 0.1):
                    continue
                y = cand[0][1]
                px, lx = parts(x)
                py, ly = parts(y)
                off = ""
                if px == py and lx.isdigit() and ly.isdigit():
                    off = int(ly) - int(lx)
                k[2] += 1
                shifts.append((kit, v.name[:40], r["num"], r["name"][:50], x, y, off, round(sx, 2), round(cand[0][0], 2)))
    out = Path("data/exports/_report_ref_shift.tsv")
    lines = ["комплект\tВОР\tпункт ВОР\tнаименование\tссылка X\tлучше Y\tсдвиг\tоценка X\tоценка Y"]
    lines += ["\t".join(str(c) for c in s) for s in shifts]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nстрок ВОР с одной ссылкой на существующую позицию: {total}")
    print(f"  наименование похоже на позицию по ссылке: {ok}")
    print(f"  не похоже (оценка < {LOW}): {weak}")
    print(f"  из них найдена одна явно лучшая другая позиция (сдвиг): {len(shifts)}")
    offs = defaultdict(int)
    for s in shifts:
        offs[s[6]] += 1
    print("  распределение сдвига (тот же раздел, разница номеров):", dict(sorted(offs.items(), key=lambda kv: -kv[1])))
    print("  комплектов со сдвигами:", sum(1 for k in per_kit.values() if k[2]), "из", len(per_kit))
    print("отчёт:", out)


if __name__ == "__main__":
    main()
