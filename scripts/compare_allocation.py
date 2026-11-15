"""Сверка эталона core/so_allocation.py с результатом запроса Связь_ВОР_СО (PQ).

Вход: выгрузка запроса Связь_ВОР_СО через scripts/pq_eval.ps1 (UTF-16, табуляция).
Из выгрузки берутся строки ВОР и СО каждой группы (КлючСО), эталон считает всё заново и сравнивает с запросом:
СО_УчтеноОдинРаз, СтатусПары, ОценкаПары, Сравнимо, СО_Справочно, ВОР_УчтеноОдинРаз.

Запуск (из venv):  python -X utf8 scripts/compare_allocation.py <выгрузка.txt> [<выгрузка2.txt> ...]
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.so_allocation import allocate_detail  # noqa: E402

FIELDS = ("доля", "статус", "оценка", "сравнимо", "справочно")


def num(x):
    x = (x or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except ValueError:
        return None


def to_int(x):
    try:
        return int(float((x or "0").replace(",", ".")))
    except ValueError:
        return 0


def load(path):
    with open(path, encoding="utf-16", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-6


def compare(path):
    rows = load(path)
    groups = defaultdict(list)
    for r in rows:
        groups[r["КлючСО"]].append(r)
    total = 0
    bad = defaultdict(int)
    mism = []
    pairs = []
    pq_all = {}
    for key, g in groups.items():
        vkeys, skeys = {}, {}
        for r in g:
            vkeys.setdefault(r["ИдСтроки"], r)
            sk = (r["СО_ИмяФайла"], r["СО_Таблица"], r["СО_Строка"])
            skeys.setdefault(sk, r)
        vids = sorted(vkeys, key=lambda k: (vkeys[k]["ИмяФайла"], to_int(vkeys[k]["Таблица"]), to_int(vkeys[k]["Строка"])))
        sids = sorted(skeys, key=lambda k: (k[0], to_int(k[1]), to_int(k[2])))
        vor = [{"name": vkeys[k]["НаименованиеРабот"], "ed": vkeys[k]["ЕдИзм"], "kol": num(vkeys[k]["КолВо"]),
                "section": vkeys[k]["Раздел"]} for k in vids]
        so = [{"name": skeys[k]["СО_НаименованиеИТехХар"], "ed": skeys[k]["СО_ЕдИзм"], "kol": num(skeys[k]["СО_КолВо"]),
               "note": skeys[k]["СО_Примечание"]} for k in sids]
        shares, _notes, info = allocate_detail(vor, so)
        py = {}
        for i, j, s, _kind, _sc in shares:
            d = info[(i, j)]
            py[(vids[i], sids[j])] = {"доля": s, "статус": d["status"], "оценка": d["score"],
                                      "сравнимо": d["comparable"], "справочно": d["ref"]}
        pq = {}
        for r in g:
            pq[(r["ИдСтроки"], (r["СО_ИмяФайла"], r["СО_Таблица"], r["СО_Строка"]))] = {
                "доля": num(r["СО_УчтеноОдинРаз"]), "статус": r["СтатусПары"], "оценка": num(r["ОценкаПары"]),
                "сравнимо": to_int(r["Сравнимо"]), "справочно": num(r["СО_Справочно"]),
                "ВОР_раз": to_int(r["ВОР_УчтеноОдинРаз"])}
        # ВОР_УчтеноОдинРаз: 1 у первой (по порядку ВОР, затем СО) пары каждой строки ВОР
        for k in py:
            v = vkeys[k[0]]
            pairs.append(((v["ИмяФайла"], to_int(v["Таблица"]), to_int(v["Строка"]), k[1][0], to_int(k[1][2])), key, k, py[k]))
        for k in set(py) | set(pq):
            total += 1
            a, b = py.get(k), pq.get(k)
            if a is None or b is None:
                bad["пара"] += 1
                mism.append((key, k[0], k[1][2], "пара есть только " + ("в PQ" if a is None else "в Python")))
                continue
            for f in FIELDS:
                x, y = a.get(f), b.get(f)
                ok = (x == y) if isinstance(x, str) or isinstance(y, str) else same(x, y)
                if not ok:
                    bad[f] += 1
                    mism.append((key, k[0], k[1][2], f, x, y, b["статус"]))
        for k, b in pq.items():
            pq_all[(key, k)] = b
    # ВОР_УчтеноОдинРаз: 1 у первой пары каждой строки ВОР во всей таблице (порядок как в запросе)
    seen = set()
    for _order, key, k, _a in sorted(pairs, key=lambda p: p[0]):
        want = 0 if k[0] in seen else 1
        seen.add(k[0])
        b = pq_all.get((key, k))
        if b is not None and b["ВОР_раз"] != want:
            bad["ВОР_раз"] += 1
            mism.append((key, k[0], k[1][2], "ВОР_раз", want, b["ВОР_раз"], b["статус"]))
    print(f"{Path(path).name}: групп {len(groups)}, пар {total}, расхождений {sum(bad.values())} {dict(bad)}")
    for m in mism[:30]:
        print("  ", m)
    return sum(bad.values())


if __name__ == "__main__":
    sys.exit(1 if sum(compare(p) for p in sys.argv[1:]) else 0)
