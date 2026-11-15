"""Сверка итогов комплекта: ВОР (ведомость), СО (спецификация) и сводная книги ВОР+СО.

Запуск (venv, -I -X utf8): python reconcile_totals.py <папка с c.xlsx v.xlsx s.xlsx> [отчёт.tsv]
  c.xlsx - книга ВОР+СО (лист «Сводная», Только_в_ВОР, Только_в_СО), v.xlsx - книга ВОР, s.xlsx - книга СО.
Исходные данные: лист ФайлBinary книг ВОР и СО (то, что читает запрос). Сводная читается как есть (значения из файла).
Сравнение по наименованию: сводная группирует по наименованию ВОР и СО. Единицы взяты из исходных таблиц.
"""
import collections
import sys

import openpyxl

d = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else d + "/reconcile.tsv"


def num(x):
    if x in (None, ""):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def unit(x):
    return (x or "").replace(".", "").strip().lower()


def table(path, sheet):
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]


vor = table(d + "/v.xlsx", "ФайлBinary")
so = table(d + "/s.xlsx", "ФайлBinary")
c = openpyxl.load_workbook(d + "/c.xlsx", data_only=True)
only_v = table(d + "/c.xlsx", "Только_в_ВОР")
only_s = table(d + "/c.xlsx", "Только_в_СО")

# Сводная в сохранённой книге может быть отфильтрована пользователем, поэтому суммы считаются
# по листу Связь_ВОР_СО по формулам мер: СуммаВОР = КолВо*ВОР_УчтеноОдинРаз,
# СуммаСО = СО_КолВо*СО_УчтеноОдинРаз (пусто, если у всех строк Сравнимо=0).
_NEED = {"СО_NПП", "КолВо", "ВОР_УчтеноОдинРаз", "Сравнимо", "СО_КолВо", "СО_УчтеноОдинРаз",
         "НаименованиеРабот", "СО_НаименованиеИТехХар"}
if ("Связь_ВОР_СО" not in c.sheetnames or c["Связь_ВОР_СО"].max_row < 2
        or not _NEED <= {v for v in next(c["Связь_ВОР_СО"].iter_rows(max_row=1, values_only=True)) if v}):
    # Листа связи нет (данные только в модели): читаем сводную как есть, она должна быть без фильтров
    if "Связь_ВОР_СО" not in c.sheetnames:
        _why = "нет листа Связь_ВОР_СО"
    elif c["Связь_ВОР_СО"].max_row < 2:
        _why = "лист Связь_ВОР_СО пуст"
    else:
        _hdr = {v for v in next(c["Связь_ВОР_СО"].iter_rows(max_row=1, values_only=True)) if v}
        _why = ("лист Связь_ВОР_СО неполный (нет столбцов: " + ", ".join(sorted(_NEED - _hdr))
                + "; в нём " + str(len(_hdr)) + " столбцов)")
    print("ВНИМАНИЕ: " + _why + ", суммы взяты из сводной (она не должна быть отфильтрована)")
    piv = []
    cur = None
    srows = list(c["Сводная"].iter_rows(values_only=True))
    hdr = next((i for i, r in enumerate(srows) if r[0] == "Названия строк"), 2)
    for r in srows[:hdr]:
        if r[0] and r[1] not in (None, "All", "(Все)"):
            print("ВНИМАНИЕ: фильтр сводной", r[0], "=", r[1], "- итоги неполные")
    for r in srows[hdr + 1:]:
        name, b, s, p = r[:4]
        if name is None or name == "Общий итог":
            continue
        if p is None and b is None and s is None:
            cur = name
        else:
            piv.append({"vor": cur, "so": name, "b": num(b), "c": num(s), "pts": p})
    link = []
else:
    link = table(d + "/c.xlsx", "Связь_ВОР_СО")
agg = {}
for r in link:
    if r.get("СО_NПП") in (None, ""):
        continue
    k = (r["НаименованиеРабот"], r["СО_НаименованиеИТехХар"])
    e = agg.setdefault(k, {"b": 0.0, "c": 0.0, "cmp": 0, "pts": set()})
    e["b"] += (num(r["КолВо"]) or 0) * (num(r["ВОР_УчтеноОдинРаз"]) or 0)
    if num(r["Сравнимо"]):
        e["cmp"] += 1
        e["c"] += (num(r["СО_КолВо"]) or 0) * (num(r["СО_УчтеноОдинРаз"]) or 0)
    e["pts"].add(str(r["СО_NПП"]))

vor_status = collections.defaultdict(set)
stat_cnt = collections.Counter()
for r in link:
    st = r.get("СтатусПары")
    if st:
        vor_status[r["НаименованиеРабот"]].add(st)
        stat_cnt[st] += 1

if link:
    # piv в том же виде, что и при чтении сводной; пусто (None) там, где сравнить нельзя
    piv = [{"vor": k[0], "so": k[1], "b": e["b"], "c": e["c"] if e["cmp"] else None,
            "pts": ",".join(sorted(e["pts"]))} for k, e in agg.items()]


# индексы исходных данных по наименованию
v_by = collections.defaultdict(list)
for r in vor:
    v_by[r["НаименованиеРабот"]].append(r)
s_by = collections.defaultdict(list)
for r in so:
    s_by[r["НаименованиеИТехХар"]].append(r)


def sum_by_unit(rows, kol, ed):
    t = collections.defaultdict(float)
    for r in rows:
        t[unit(r[ed])] += num(r[kol]) or 0
    return t


v_tot = sum_by_unit(vor, "КолВо", "ЕдИзм")
s_tot = sum_by_unit(so, "КолВо", "ЕдИзм")

# сводная по единицам (единица - по исходной таблице)
pb = collections.defaultdict(float)
pc = collections.defaultdict(float)
for p in piv:
    uv = unit((v_by.get(p["vor"]) or [{"ЕдИзм": "?"}])[0]["ЕдИзм"])
    us = unit((s_by.get(p["so"]) or [{"ЕдИзм": "?"}])[0]["ЕдИзм"])
    pb[uv] += p["b"] or 0
    pc[us] += p["c"] or 0

for p in piv:
    for key, idx, lab in (("vor", v_by, "ВОР"), ("so", s_by, "СО")):
        if p[key] not in idx and p["b" if key == "vor" else "c"]:
            print("НЕТ в исходной таблице", lab, repr(p[key]), "значение", p["b" if key == "vor" else "c"])

ov = sum_by_unit(only_v, "КолВо", "ЕдИзм")
os_ = sum_by_unit(only_s, "КолВо", "ЕдИзм")

lines = []


def P(*a):
    lines.append("\t".join(str(x) for x in a))
    print(*a)


def f(x):
    return round(x, 3)


P("== ИТОГО (все единицы вместе, для ориентира)")
P("ВОР исходная", f(sum(v_tot.values())), "строк", len(vor))
P("Сводная СуммаВОР", f(sum(pb.values())))
P("СО исходная", f(sum(s_tot.values())), "строк", len(so))
P("Сводная СуммаСО", f(sum(pc.values())))
P()
P("== ПО ЕДИНИЦАМ")
P("ед.", "ВОР исх.", "Только_в_ВОР", "Сводная ВОР", "разница ВОР", "СО исх.", "Только_в_СО", "Сводная СО", "разница СО")
for u in sorted(set(v_tot) | set(s_tot) | set(pb) | set(pc)):
    P(u or "(пусто)", f(v_tot[u]), f(ov[u]), f(pb[u]), f(v_tot[u] - ov[u] - pb[u]),
      f(s_tot[u]), f(os_[u]), f(pc[u]), f(s_tot[u] - os_[u] - pc[u]))

# построчно: ВОР
P()
P("== ВОР: наименования, у которых СуммаВОР в сводной не равна исходной сумме (за вычетом Только_в_ВОР)")
ov_names = collections.Counter(r["НаименованиеРабот"] for r in only_v)
pv = collections.defaultdict(float)
pv_seen = set()
for p in piv:
    pv[p["vor"]] += p["b"] or 0
    pv_seen.add(p["vor"])
P("пункт", "наименование ВОР", "ед.", "исходно", "в Только_в_ВОР", "в сводной", "причина")
resid_v = 0.0
expl_v = 0.0
defect_v = 0.0
for n, rows in v_by.items():
    src = sum(num(r["КолВо"]) or 0 for r in rows)
    onl = sum(num(r["КолВо"]) or 0 for r in only_v if r["НаименованиеРабот"] == n)
    got = pv.get(n, 0.0)
    if abs(src - onl - got) > 1e-6:
        links = [p for p in piv if p["vor"] == n]
        if n not in pv_seen:
            why = "нет в сводной"
        elif all(p["b"] is None for p in links):
            why = "в сводной пусто (нет сравнимой строки СО)"
        elif src > got:
            why = "часть строк ВОР с этим наименованием в сводной не учтена"
        else:
            why = "в сводной больше, чем в ВОР"
        if why.startswith("в сводной пусто"):
            # пусто: «нет аналога (другая единица)» по замыслу или «ВОР без доли» (дефект ссылки)
            if "ВОР без доли" in vor_status.get(n, set()):
                defect_v += src - onl - got
            else:
                expl_v += src - onl - got
        else:
            resid_v += src - onl - got
        P(",".join(sorted({str(r["NПП"]) for r in rows})), n[:70], rows[0]["ЕдИзм"], f(src), f(onl), f(got), why)

P()
P("== СО: наименования, у которых СуммаСО в сводной не равна исходной сумме (за вычетом Только_в_СО)")
os_names = collections.defaultdict(float)
for r in only_s:
    os_names[r["НаименованиеИТехХар"]] += num(r["КолВо"]) or 0
ps = collections.defaultdict(float)
ps_seen = set()
for p in piv:
    ps[p["so"]] += p["c"] or 0
    ps_seen.add(p["so"])
P("пункт", "наименование СО", "ед.", "исходно", "в Только_в_СО", "в сводной", "причина")
resid_s = 0.0
for n, rows in s_by.items():
    src = sum(num(r["КолВо"]) or 0 for r in rows)
    onl = os_names.get(n, 0.0)
    got = ps.get(n, 0.0)
    if abs(src - onl - got) > 1e-6:
        if n not in ps_seen:
            why = "нет в сводной"
        elif src - onl > got:
            why = "сводная меньше: объём не учтён (строка СО без своей строки ВОР или Сравнимо=0)"
        else:
            why = "сводная больше"
        resid_s += src - onl - got
        P(",".join(sorted({str(r["NПП"]) for r in rows})), n[:70], rows[0]["ЕдИзм"], f(src), f(onl), f(got), why)

P()
P("== Только_в_СО: строки СО, на которые не ссылается ни одна строка ВОР (в сводную не входят)")
P("NПП", "наименование СО", "ед.", "кол-во", "примечание")
for r in only_s:
    P(r["NПП"], str(r["НаименованиеИТехХар"])[:60], r["ЕдИзм"], r["КолВо"], r["Примечание"])
P()
P("== Только_в_ВОР: строки ВОР без пары в СО (в сводную не входят)")
P("NПП", "наименование ВОР", "ед.", "кол-во", "причина")
for r in only_v:
    P(r["NПП"], str(r["НаименованиеРабот"])[:60], r["ЕдИзм"], r["КолВо"], r["Причина"])
P()
P("== Сводная: строки, где СуммаВОР не равна СуммаСО (ВОР и СО связаны, но объёмы разные)")
P("пункт СО", "ВОР", "СО", "СуммаВОР", "СуммаСО")
for p in piv:
    if (p["b"] or 0) != (p["c"] or 0):
        P(p["pts"], str(p["vor"])[:60], str(p["so"])[:40], p["b"], p["c"])
P()
P("== Сводная: разница СуммаВОР - СуммаСО по видам строк и единицам")
cls = collections.defaultdict(lambda: [0, 0.0, 0.0])
for p in piv:
    b, s = p["b"], p["c"]
    uv = unit((v_by.get(p["vor"]) or [{"ЕдИзм": "?"}])[0]["ЕдИзм"])
    us = unit((s_by.get(p["so"]) or [{"ЕдИзм": "?"}])[0]["ЕдИзм"])
    if (b or 0) == (s or 0):
        k = "1 объёмы равны"
    elif not b and s:
        k = "2 СО есть, ВОР здесь 0 (строка ВОР учтена в другой строке сводной)"
    elif b and s:
        k = "3 обе есть, объёмы разные"
    elif b and not s:
        k = "4 ВОР есть, СО пусто (нет сравнимой строки СО)"
    else:
        k = "5 обе пусто"
    e = cls[(k, uv if b else us)]
    e[0] += 1
    e[1] += b or 0
    e[2] += s or 0
P("вид", "ед.", "строк", "СуммаВОР", "СуммаСО", "ВОР-СО")
for (k, u), (n, b, s) in sorted(cls.items()):
    P(k, u, n, f(b), f(s), f(b - s))
P()
P("== ПОЯСНЕНИЯ (формируются автоматически по данным комплекта)")
P("Что", "Объяснение")


def by_unit_txt(t):
    return "; ".join(f"{u or '(пусто)'} {f(v)}" for u, v in sorted(t.items()) if v)


if only_v:
    rs = collections.Counter(str(r.get("Причина") or "без причины") for r in only_v)
    P("ВОР → сводная: Только_в_ВОР", f"{len(only_v)} строк без пары в СО, в сводную не входят: "
      + by_unit_txt(ov) + ". Причины: " + "; ".join(f"{k} — {n}" for k, n in rs.most_common()))
if only_s:
    P("СО → сводная: Только_в_СО", f"{len(only_s)} строк, на которые не ссылается ни одна строка ВОР: "
      + by_unit_txt(os_) + ".")
for st, n in stat_cnt.most_common():
    txt = {
        "нет аналога (другая единица)": "строка ВОР в единице, которой нет у связанных строк СО; объём не пересчитывается, СуммаСО пусто",
        "ВОР без доли": "объём СО отдан другой строке ВОР; проверить ссылку (см. лист Ошибки)",
        "единицы разные": "единицы ВОР и СО различаются, объём отнесён первой строке",
        "операция над тем же материалом": "несколько строк ВОР на один материал; учтена первая, остальные 0",
        "доля по КолВо": "объём СО разделён пропорционально КолВо ВОР",
        "проверить вручную": "связь неоднозначна, объём отнесён первой строке",
    }.get(st)
    if txt:
        P("Статус «" + st + "»", f"{n} строк: {txt}")
sh = 0
shs = []
if "Ошибки" in c.sheetnames:
    for row in c["Ошибки"].iter_rows(values_only=True):
        t = " ".join(str(x) for x in row if x not in (None, ""))
        if "сдвинута" in t:
            sh += 1
            if len(shs) < 5:
                shs.append(t[:140])
if sh:
    P("Сдвинутые ссылки", f"{sh} подсказок на листе «Ошибки»: " + " | ".join(shs))
P("Разные единицы", "Итоги по единицам не складываются; сравнивайте таблицу «По единицам измерения».")
P()
P("остаток объяснённый: ВОР пусто в сводной (нет аналога в СО / другая единица)", f(expl_v))
P("остаток к проверке: ВОР без доли (ссылка сдвинута или объём СО отдан другой строке, см. лист Ошибки)", f(defect_v))
P("остаток необъяснённого ВОР (сумма по наименованиям, разные единицы вместе)", f(resid_v))
P("остаток необъяснённого СО", f(resid_s))
with open(out, "w", encoding="utf-8-sig") as fh:
    fh.write("\n".join(lines))
