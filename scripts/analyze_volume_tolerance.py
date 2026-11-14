"""Реальные расхождения объёмов ВОР и СО по всем комплектам из РД/ (для выбора допуска «примерно равно»).

Для каждой пары «ВОР + СО» одной папки: ссылки ВОР «.СО (поз. X)» -> группа (строки ВОР, строки СО с номером X),
распределение core.so_allocation.allocate, затем сравнение объёмов при одной единице измерения:
  pair1   пара один к одному в группе, где одна строка ВОР и одна строка СО (шум округления);
  pairN   пара в группе из нескольких строк;
  sum     группа «несколько ВОР -> одна строка СО»: сумма КолВо ВОР против СО, и каждая строка против СО.
Отчёты: data/exports/_report_volume_tolerance.tsv (группы «несколько ВОР -> одна СО»), сводка в stdout.

Запуск (из venv):  python -I -X utf8 scripts/analyze_volume_tolerance.py [РД] [data/converted] [подстрока пути]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402
from core.so_allocation import allocate  # noqa: E402
from find_dup_cases import is_so, is_vor, norm, resolve, vor_refs  # noqa: E402

NUM = re.compile(r"\d+(?:[.,]\d+)?")
PART = re.compile(r"назем|надзем|подзем")


def qty(text):
    m = NUM.search((text or "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def read(path, kind):
    """-> [{num, name, ed, kol, note, ref, section}]"""
    with numbering_fixed(str(path)) as fixed:
        d = docx.Document(fixed)
    out, section = [], ""
    for tb in d.tables:
        rows = []
        for r in tb.rows:
            try:
                rows.append([c.text.strip() for c in r.cells])
            except Exception:
                rows.append([])
        mp = None
        start = 0
        for i, cells in enumerate(rows[:6]):
            h = [norm(c) for c in cells]
            if not any("наименование" in x for x in h):
                continue
            if kind == "so":
                ok = any(x.startswith("поз") or x.startswith("№") for x in h)
            else:
                ok = any("№" in x for x in h)
            if ok:
                f = lambda pred: next((j for j, x in enumerate(h) if pred(x)), None)  # noqa: E731
                mp = dict(
                    num=f(lambda x: x.startswith("поз") or x.startswith("№")),
                    name=f(lambda x: "наименование" in x),
                    ed=f(lambda x: x.startswith("ед")),
                    kol=f(lambda x: x.startswith("кол")),
                    note=f(lambda x: "примечание" in x),
                    n=len(h),
                )
                start = i + 1
                break
        if mp is None or None in (mp["num"], mp["name"], mp["ed"], mp["kol"]):
            continue
        for cells in rows[start:]:
            if len(cells) != mp["n"]:
                continue
            name = cells[mp["name"]]
            if re.fullmatch(r"\d{1,2}", name.strip()):
                continue
            num = cells[mp["num"]].strip().rstrip(".")
            others = [c for j, c in enumerate(cells) if j != mp["name"] and c.strip()]
            if not num and name and not others:
                section = name.strip()
                continue
            rest = " ".join(x for j, x in enumerate(cells) if j != mp["name"])
            out.append(dict(num=num, name=name, ed=cells[mp["ed"]], kol=qty(cells[mp["kol"]]),
                            note=cells[mp["note"]] if mp["note"] is not None else "", ref=rest, section=section))
    for i, r in enumerate(out[:-1]):
        n = out[i + 1]
        if not r["num"] and r["name"] and n["num"] and norm(n["name"])[:20] == norm(r["name"])[:20]:
            r["num"] = n["num"]
    return [r for r in out if r["num"]]


def unit(x):
    return (x or "").replace(".", "").strip().lower()


def rel(a, b):
    return abs(a - b) / b if b else None


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
    pair1, pairN, groups = [], [], []
    nk = 0
    for folder, (vors, sos) in kits.items():
        if not vors or not sos:
            continue
        data_so = {}
        for s in sos:
            sp = resolve(s, conv)
            if sp:
                try:
                    data_so[s] = read(sp, "so")
                except Exception as e:  # noqa: BLE001
                    print("ошибка СО", s.name, e)
        for v in vors:
            vp = resolve(v, conv)
            if not vp or not data_so:
                continue
            try:
                vrows = read(vp, "vor")
            except Exception as e:  # noqa: BLE001
                print("ошибка ВОР", v.name, e)
                continue
            refs = defaultdict(list)
            for r in vrows:
                for x in set(vor_refs(r["ref"])):
                    refs[x].append(r)
            best, hits = None, 0
            for s, rows in data_so.items():
                nums = {r["num"] for r in rows}
                h = len([x for x in refs if x in nums])
                if h > hits:
                    best, hits = s, h
            if best is None:
                continue
            nk += 1
            kit = str(folder.relative_to(root))
            so_by = defaultdict(list)
            for r in data_so[best]:
                so_by[r["num"]].append(r)
            for ref, vr in refs.items():
                sr = so_by.get(ref)
                if not sr:
                    continue
                res, notes = allocate(vr, sr)
                for i, j, sh in res:
                    if sh <= 0 or vr[i]["kol"] is None or sr[j]["kol"] is None:
                        continue
                    if unit(vr[i]["ed"]) != unit(sr[j]["ed"]):
                        continue
                    d = rel(vr[i]["kol"], sr[j]["kol"])
                    if d is None:
                        continue
                    if len(vr) == 1 and len(sr) == 1:
                        pair1.append((d, kit, ref, vr[i]["kol"], sr[j]["kol"]))
                    elif len(vr) == 1 or sh == 1.0:
                        pairN.append((d, kit, ref, vr[i]["kol"], sr[j]["kol"]))
                if len(vr) >= 2 and len(sr) == 1:
                    s0 = sr[0]
                    same = [r for r in vr if unit(r["ed"]) == unit(s0["ed"]) and r["kol"]]
                    tot = sum(r["kol"] for r in same)
                    parts = [tuple(sorted(set(PART.findall(norm(r["name"]))))) for r in vr]
                    secs = {r["section"] for r in vr}
                    groups.append(dict(
                        kit=kit, ref=ref, n=len(vr), so=s0["kol"], ed=s0["ed"], units=sorted({unit(r["ed"]) for r in vr}),
                        n_same=len(same), sum_d=rel(tot, s0["kol"]) if s0["kol"] and same else None,
                        each=[rel(r["kol"], s0["kol"]) for r in same] if s0["kol"] else [],
                        same_section=len(secs) == 1, same_part=len(set(parts)) == 1, parts=parts,
                        prop=any(n[0] == "доля по КолВо" for n in notes),
                        vol=[r["kol"] for r in vr], names=[r["name"][:45] for r in vr], so_name=s0["name"][:45]))
            print("комплект:", folder.name[:60], "ВОР:", v.name[:40], "->", best.name[:40], "групп", len(refs))
            sys.stdout.flush()
    out = Path("data/exports/_report_volume_tolerance.tsv")
    lines = ["комплект\tпункт\tn ВОР\tСО\tед СО\tед ВОР\tсумма same\tотклонение суммы\tотклонения строк\tодин раздел\tодна часть\tчасти\tобъёмы ВОР\tделение по КолВо\tнаименования"]
    for g in groups:
        lines.append("\t".join(str(x) for x in [
            g["kit"], g["ref"], g["n"], g["so"], g["ed"], ",".join(g["units"]), g["n_same"],
            "" if g["sum_d"] is None else round(g["sum_d"], 4), ";".join(f"{e:.3f}" for e in g["each"] if e is not None),
            g["same_section"], g["same_part"], g["parts"], g["vol"], g["prop"], " | ".join(g["names"]) + " => " + g["so_name"]]
        ).replace("\r", " ").replace("\n", " "))
    out.write_text("\n".join(lines), encoding="utf-8")

    def hist(name, arr):
        ds = sorted(x[0] for x in arr)
        print(f"\n{name}: {len(ds)} пар")
        if not ds:
            return
        eq = sum(1 for d in ds if d < 1e-9)
        print("  точно равны:", eq)
        for lim in (0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5):
            print(f"  <= {lim:.1%}: {sum(1 for d in ds if d <= lim)}")
        print("  больше 50%:", sum(1 for d in ds if d > 0.5))
        far = [x for x in arr if 1e-9 < x[0] <= 0.25]
        for x in sorted(far)[:15]:
            print("   ", f"{x[0]:.3%}", x[1][-40:], "поз.", x[2], "ВОР", x[3], "СО", x[4])
    print("\nкомплектов (ВОР+СО):", nk)
    hist("pair1 (одна строка ВОР и одна СО)", pair1)
    hist("pairN (пары в больших группах)", pairN)
    print("\nгруппы «несколько ВОР -> одна СО»:", len(groups))
    print("отчёт:", out)


if __name__ == "__main__":
    main()
