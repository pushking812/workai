"""Поиск комплектов, где остатки «только в ВОР» и «только в СО» сопоставляются по наименованию.

Для каждой пары «спецификация + ВОР» в РД/ (как в find_dup_cases.py):
  - строки ВОР без пары по номеру: нет ссылки «СО (поз. X)» (и «поз.» в наименовании) или ни одна
    ссылка не найдена среди позиций СО;
  - строки СО, на которые не ссылается ни одна строка ВОР;
  - к ним применяется правило scripts/check_name_match.match (то же, что блок 6 запроса Ошибки.pq).
Печатает по комплекту число остатков и найденных пар, пишет tsv со всеми парами.
Приближение: связь по номеру считается по ссылкам в тексте, без даты и без «в составе».

Запуск (из venv):  python -I -X utf8 scripts/find_name_match_cases.py [РД] [data/converted] [отчёт.tsv]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from check_name_match import match  # noqa: E402
from find_dup_cases import NUM_RE, is_so, is_vor, read_rows, resolve, vor_refs  # noqa: E402
from find_spec_in_name import POS_RE  # noqa: E402

NUM_ONLY = re.compile(r"\d+(?:\.\d+)*")


# «ЕСТ-…-ЭК.СО - п.1», «…СО - \nп.1.1», «СО (поз. 5)»
# «…АПТ.С поз.1», «…ЭС1.СО, поз. 25»
REF2_RE = re.compile(r"\.\s*СО?\s*[(–—,-]*\s*(?:поз|п)\.?\s*([^)\n;]*)", re.I)


def refs_of(name, ref):
    out = set(vor_refs(ref))
    for m in REF2_RE.finditer(ref or ""):
        out |= set(NUM_RE.findall(m.group(1)))
    for m in POS_RE.findall(name or ""):
        out |= set(NUM_RE.findall(m))
    return out


def analyse(so_path, vor_path):
    so = read_rows(so_path, "so")
    vor = read_rows(vor_path, "vor")
    so_pos = {r[0] for r in so}
    used = set()
    for r in vor:
        used |= refs_of(r[1], r[2])
    only_vor = [r for r in vor if r[1].strip() and not (refs_of(r[1], r[2]) & so_pos)]
    only_so = [r for r in so if r[0] not in used and r[1].strip()]
    v = [{"ШифрПроекта": "k", "НомИзмПроекта": 1, "NПП": r[0], "НаименованиеРабот": r[1]} for r in only_vor]
    s = [{"ШифрПроекта": "k", "НомИзмПроекта": 1, "NПП": r[0], "НаименованиеИТехХар": r[1], "Примечание": r[2]}
         for r in only_so]
    return len(vor), len(so), len(used), v, s, match(v, s)


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "РД")
    conv = Path(sys.argv[2] if len(sys.argv) > 2 else "data/converted")
    rep = Path(sys.argv[3] if len(sys.argv) > 3 else "data/exports/_report_name_match.tsv")
    by_dir = defaultdict(lambda: {"so": [], "vor": []})
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".doc", ".docx") or p.name.startswith("~$"):
            continue
        if "Обосновывающие" in str(p):
            continue
        if is_vor(p.name):
            by_dir[p.parent]["vor"].append(p)
        elif is_so(p.name):
            by_dir[p.parent]["so"].append(p)
    lines = ["комплект\tстатус\tВОР №\tВОР наименование\tСО №\tСО наименование\tСО примечание"]
    pairs_total = 0
    for d, g in sorted(by_dir.items()):
        for vp0 in g["vor"]:
            vp = resolve(vp0, conv)
            best = None
            for sp0 in g["so"]:
                sp = resolve(sp0, conv)
                if vp is None or sp is None:
                    continue
                try:
                    a = analyse(sp, vp)
                except Exception as e:  # noqa: BLE001
                    print("ошибка", sp0.name, vp0.name, e)
                    continue
                if best is None or a[2] > best[0][2]:
                    best = (a, sp0)
            if best is None:
                continue
            (nv, ns, nrefs, v, s, res), sp0 = best
            kit = str(d.relative_to(root))
            pairs = [x for x in res if x[2] == "по наименованию"]
            amb = [x for x in res if x[2] != "по наименованию"]
            pairs_total += len(res)
            print(f"{len(pairs):3d} пар, {len(amb):3d} неоднозн. | остатки ВОР {len(v):3d}/{nv:3d}, СО {len(s):3d}/{ns:3d}"
                  f" | ссылок {nrefs:3d} | {kit}")
            for i, j, st in res:
                lines.append("\t".join([kit, st, v[i]["NПП"], v[i]["НаименованиеРабот"].replace("\n", " "),
                                        s[j]["NПП"], s[j]["НаименованиеИТехХар"].replace("\n", " "),
                                        (s[j]["Примечание"] or "").replace("\n", " ")]))
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("\n".join(lines), encoding="utf-8")
    print("всего кандидатов", pairs_total, "->", rep)


if __name__ == "__main__":
    main()
