"""Связь СВОР с ВОР (из общей книги ВОР+СО) по наименованию работ: количество «по РД» СВОР должно быть равно КолВо ВОР.

Правила:
1. Строки СВОР с Р = 0 (удалена) в ВОР не ищем: их там быть не должно.
2. Режим «имя»: наименование совпало после нормализации (регистр, ё, пробелы и знаки) и единица та же;
   количества суммируются по ключу (имя, единица) с обеих сторон.
3. Режим «имя без хвоста»: у остатка отрезан хвост «Наземная часть ...» (числа по частям здания), суммы по голове имени.
4. Режим «слова»: для остатка наборы слов (core/name_link.words, не меньше двух) совпали, единица та же, кандидат единственный.
5. Допуск объёмов 0,5% (как в ВОР+СО).
Строки СВОР - из core/svor.py, строки ВОР - {"Наименование", "Ед", "Кол", "Номер", "Шифр"}.
"""
import re

from core.name_link import words

TOLERANCE = 0.005


def _t(x):
    return "" if x is None else str(x)


def norm_name(text):
    return re.sub(r"[^0-9a-zа-я]", "", _t(text).lower().replace("ё", "е"))


def norm_unit(text):
    return _t(text).lower().replace("ё", "е").strip(" .")


_TAIL = re.compile(r"\s(?:наземн|подземн)\w*\s+част", re.IGNORECASE)


def head(name):
    """Наименование без хвоста «Наземная/Подземная часть ...» (там числа по частям здания)."""
    m = _TAIL.search(_t(name))
    return _t(name)[:m.start()] if m else _t(name)


def vor_rows_from_strings(rows):
    """Строки ВОР_Строки (книга ВОР/ВОР+СО, имена столбцов PQ) -> {"Наименование", "Ед", "Кол", "Номер", "Шифр"}.
    Как в запросе ВОР_Строки: строки без ИдСтроки и строка «Итог» не берутся."""
    out = []
    for r in rows:
        if not r.get("ИдСтроки") or r.get("ИдСтроки") == "Итог":
            continue
        out.append({"Наименование": r.get("НаименованиеРабот"), "Ед": r.get("ЕдИзм"), "Кол": r.get("КолВо"),
                    "Номер": r.get("NПП"), "Шифр": r.get("ШифрПроекта") or ""})
    return out


def read_vor_book(path, sheet="ФайлBinary"):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        it = wb[sheet].iter_rows(values_only=True)
        head = next(it)
        return vor_rows_from_strings(dict(zip(head, row)) for row in it)
    finally:
        wb.close()


def _num(x):
    try:
        return float(_t(x).replace(",", ".").replace(" ", ""))
    except ValueError:
        return 0.0


def _status(svor_qty, vor_qty):
    if abs(svor_qty - vor_qty) <= TOLERANCE * max(abs(svor_qty), abs(vor_qty)):
        return "совпало"
    return "СВОР больше" if svor_qty > vor_qty else "ВОР больше"


def link(svor_rows, vor_rows):
    """Пары СВОР-ВОР. Запись: {"Статус", "Режим", "Наименование", "Ед", "СВОР_Р", "ВОР", "Разница", "СтрокСВОР", "СтрокВОР"}.
    Статусы: совпало / СВОР больше / ВОР больше / только в СВОР / только в ВОР / удалена в СВОР."""
    out = []
    sv, deleted = {}, []
    for r in svor_rows:
        if not r.get("Ед") and r.get("Р") is None:
            continue
        if (r.get("Р") or 0) == 0:
            deleted.append(r)
            continue
        g = sv.setdefault((norm_name(r["Наименование"]), norm_unit(r["Ед"])),
                          {"Наименование": r["Наименование"], "Ед": r["Ед"], "Кол": 0.0, "Строк": 0, "Слова": words(r["Наименование"])})
        g["Кол"] += r["Р"] or 0.0
        g["Строк"] += 1
    vo = {}
    for r in vor_rows:
        g = vo.setdefault((norm_name(r["Наименование"]), norm_unit(r["Ед"])),
                          {"Наименование": r["Наименование"], "Ед": r["Ед"], "Кол": 0.0, "Строк": 0, "Слова": words(r["Наименование"])})
        g["Кол"] += _num(r["Кол"])
        g["Строк"] += 1

    used = set()

    def pair(skey, vkey, mode):
        used.add(vkey)
        a, b = sv[skey], vo[vkey]
        out.append({"Статус": _status(a["Кол"], b["Кол"]), "Режим": mode, "Наименование": a["Наименование"], "Ед": a["Ед"],
                    "СВОР_Р": round(a["Кол"], 6), "ВОР": round(b["Кол"], 6), "Разница": round(a["Кол"] - b["Кол"], 6),
                    "СтрокСВОР": a["Строк"], "СтрокВОР": b["Строк"]})

    rest = []
    for k in sv:
        if k in vo:
            pair(k, k, "имя")
        else:
            rest.append(k)

    # Режим «имя без хвоста»: у остатка отрезаем «Наземная часть выше отм.0,000 – N шт.» и суммируем по голове имени.
    def merge(groups, keys):
        m = {}
        for k in keys:
            g = groups[k]
            mk = (norm_name(head(g["Наименование"])), k[1])
            t = m.setdefault(mk, {"Наименование": g["Наименование"], "Ед": g["Ед"], "Кол": 0.0, "Строк": 0, "Слова": g["Слова"], "Ключи": []})
            t["Кол"] += g["Кол"]
            t["Строк"] += g["Строк"]
            t["Ключи"].append(k)
        return m

    sv_rest = merge(sv, rest)
    vo_rest = merge(vo, [k for k in vo if k not in used])
    rest = []
    for mk, a in sv_rest.items():
        b = vo_rest.get(mk)
        if b and mk[0]:
            used.update(b["Ключи"])
            out.append({"Статус": _status(a["Кол"], b["Кол"]), "Режим": "имя без хвоста", "Наименование": a["Наименование"],
                        "Ед": a["Ед"], "СВОР_Р": round(a["Кол"], 6), "ВОР": round(b["Кол"], 6),
                        "Разница": round(a["Кол"] - b["Кол"], 6), "СтрокСВОР": a["Строк"], "СтрокВОР": b["Строк"]})
        else:
            rest += a["Ключи"]
    for k in rest:
        w = set(sv[k]["Слова"])
        cands = [v for v in vo if v not in used and v[1] == k[1] and len(w) >= 2 and w == set(vo[v]["Слова"])]
        if len(cands) == 1:
            pair(k, cands[0], "слова")
        else:
            a = sv[k]
            out.append({"Статус": "только в СВОР", "Режим": "", "Наименование": a["Наименование"], "Ед": a["Ед"],
                        "СВОР_Р": round(a["Кол"], 6), "ВОР": 0.0, "Разница": round(a["Кол"], 6),
                        "СтрокСВОР": a["Строк"], "СтрокВОР": 0})
    for v, b in vo.items():
        if v not in used:
            out.append({"Статус": "только в ВОР", "Режим": "", "Наименование": b["Наименование"], "Ед": b["Ед"],
                        "СВОР_Р": 0.0, "ВОР": round(b["Кол"], 6), "Разница": round(-b["Кол"], 6),
                        "СтрокСВОР": 0, "СтрокВОР": b["Строк"]})
    for r in deleted:
        out.append({"Статус": "удалена в СВОР", "Режим": "", "Наименование": r["Наименование"], "Ед": r["Ед"],
                    "СВОР_Р": 0.0, "ВОР": 0.0, "Разница": 0.0, "СтрокСВОР": 1, "СтрокВОР": 0})
    return out
