"""Связь кабельного журнала (КЖ) со спецификацией оборудования (СО): марка + сечение.

Правила (разведка на СДС: 5 из 10 групп КЖ совпали с СО точно, ещё одна — по словам):
1. Ключ - (марка, сечение) после нормализации: регистр, ё->е, кириллические двойники латиницы
   (А/A, х/x, с/c ...), `х`/`×`/`*` -> `x`, запятая -> точка, пробелы убраны.
2. Количества суммируются по ключу в обеих сторонах (КЖ - метры, СО - м или км).
3. Режим «ключ»: ключи равны. Режим «слова»: сечение равно, а значимые слова марки КЖ целиком
   входят в наименование и тип СО, кандидат единственный.
4. Допуск объёмов 0,5% (как в ВОР+СО).
Строки - словари:  КЖ {"Марка", "Сечение", "Длина"};  СО {"Наименование", "Тип", "Ед", "Кол"}.
"""
import re

TOLERANCE = 0.005

# Кириллица, неотличимая от латиницы -> латиница (после lower()).
_LOOKALIKE = str.maketrans("авекмнорстух", "abekmhopctyx")
_SEC_RE = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[xх×*]\s*\d+(?:[.,]\d+)?)+", re.IGNORECASE)
_STOP = {"cat", "cat.", "кат", "кат.", "категории", "нг(а)", "нг", "кабель", "провод", "solid"}
_CABLE_WORD = re.compile(r"кабел|провод|витая|шнур", re.IGNORECASE)
_NOT_CABLE = re.compile(r"канал|лоток|короб|труб|штанг|хомут|держател", re.IGNORECASE)
_CAT_RE = re.compile(r"(?<![^\W\d_])(?:cat|кат)\.?\s*(?=\d)")  # «Cat. 5e», «кат.5E» -> «5e»
_SPLIT = re.compile(r"[\s,;()\[\]«»\"']+")


def _t(x):
    return "" if x is None else str(x)


def to_number(text):
    s = _t(text).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_section(text):
    """'4х2х0,52' -> '4x2x0.52'. Пусто, если сечения нет."""
    m = _SEC_RE.search(_t(text))
    if not m:
        return ""
    s = m.group(0).lower().replace(" ", "").replace(",", ".")
    return re.sub(r"[хx×*]", "x", s)


def normalize_mark(text):
    """Марка без сечения: нижний регистр, двойники -> латиница, без пробелов.
    Составная ячейка («... цвет красный, ... цвет синий») даёт первую марку."""
    s = _SEC_RE.sub(" ", _t(text)).lower().replace("ё", "е")
    first = [w for w in _SPLIT.split(s) if w]
    return "".join(first[:1]).translate(_LOOKALIKE) if first else ""


def mark_words(text):
    """Значимые слова марки: нижний регистр, двойники -> латиница, без служебных."""
    s = _CAT_RE.sub(" ", _SEC_RE.sub(" ", _t(text)).lower().replace("ё", "е"))
    out = []
    for w in _SPLIT.split(s):
        w = w.strip(".")
        if w and w not in _STOP and (len(w) >= 2 or any(c.isdigit() for c in w)):
            out.append(w.translate(_LOOKALIKE))
    return list(dict.fromkeys(out))


def so_meters(unit, qty):
    """Количество СО в метрах; None, если единица не длина."""
    u = _t(unit).strip(" .").lower()
    q = to_number(qty)
    if q is None:
        return None
    if u == "м":
        return q
    if u == "км":
        return q * 1000
    return None


def kzh_groups(rows):
    """КЖ -> {(марка, сечение): {"Длина", "Строк", "Слова", "Марка"}}; строки без марки пропущены."""
    out = {}
    for r in rows:
        mark = normalize_mark(r.get("Марка"))
        if not mark:
            continue
        key = (mark, normalize_section(r.get("Сечение")))
        g = out.setdefault(key, {"Длина": 0.0, "Строк": 0, "Слова": mark_words(r.get("Марка")), "Марка": _t(r.get("Марка"))})
        g["Длина"] += to_number(r.get("Длина")) or 0.0
        g["Строк"] += 1
    return out


def so_groups(rows):
    """СО -> {(марка, сечение): {"Длина", "Строк", "Слова"}}; только строки с длиной и сечением.
    Сечение берётся из типа/марки, если там нет - из наименования; марка - тип без сечения."""
    out = {}
    for r in rows:
        m = so_meters(r.get("Ед"), r.get("Кол"))
        if m is None:
            continue
        typ, name = _t(r.get("Тип")), _t(r.get("Наименование"))
        if not _CABLE_WORD.search(name + " " + typ) or _NOT_CABLE.search(name):  # трубы, каналы, штанги - не кабель
            continue
        sec = normalize_section(typ) or normalize_section(name)
        if not sec:
            continue
        mark = normalize_mark(typ)
        key = (mark, sec)
        g = out.setdefault(key, {"Длина": 0.0, "Строк": 0, "Слова": []})
        g["Длина"] += m
        g["Строк"] += 1
        g["Слова"] = list(dict.fromkeys(g["Слова"] + mark_words(typ) + mark_words(name)))
    return out


def _status(kzh, so):
    if abs(kzh - so) <= TOLERANCE * max(abs(kzh), abs(so)):
        return "совпало"
    return "КЖ больше" if kzh > so else "СО больше"


def link_by_project(kzh_rows, so_rows):
    """link() отдельно для каждого шифра проекта (поле "Шифр" в строках КЖ и СО); в записях добавлено "Шифр".
    Строки без шифра идут в группу "" и связываются между собой."""
    codes = []
    for r in list(kzh_rows) + list(so_rows):
        c = _t(r.get("Шифр"))
        if c not in codes:
            codes.append(c)
    out = []
    for c in codes:
        part = link([r for r in kzh_rows if _t(r.get("Шифр")) == c], [r for r in so_rows if _t(r.get("Шифр")) == c])
        out += [dict(x, Шифр=c) for x in part]
    return out


def link(kzh_rows, so_rows):
    """Пары КЖ-СО. Запись: {"Статус", "Режим", "МаркаКЖ", "Сечение", "КЖ_м", "СО_м", "Разница", "КлючСО"}.
    Статусы: совпало / КЖ больше / СО больше / марка отличается (сечение и объём те же) / только в КЖ / только в СО."""
    kz, so = kzh_groups(kzh_rows), so_groups(so_rows)
    used, out = set(), []

    def pair(key, skey, mode):
        used.add(skey)
        a, b = kz[key]["Длина"], so[skey]["Длина"]
        out.append({"Статус": _status(a, b), "Режим": mode, "МаркаКЖ": kz[key]["Марка"], "Сечение": key[1],
                    "КЖ_м": round(a, 3), "СО_м": round(b, 3), "Разница": round(a - b, 3), "КлючСО": "|".join(skey)})

    rest = []
    for key in kz:
        if key in so and key not in used:
            pair(key, key, "ключ")
        else:
            rest.append(key)
    rest2 = []
    for key in rest:
        w = set(kz[key]["Слова"])
        # У КЖ нет сечения (например, «Duplex SM 9/125») - ищем только по словам марки.
        cands = [s for s in so if s not in used and (s[1] == key[1] or not key[1]) and w and w <= set(so[s]["Слова"])]
        if len(cands) == 1:
            pair(key, cands[0], "слова")
        else:
            rest2.append(key)
    for key in rest2:
        # Сечение и объём совпали, марка другая (опечатка или замена): единственный кандидат - пара для проверки.
        cands = [s for s in so if s not in used and key[1] and s[1] == key[1]
                 and _status(kz[key]["Длина"], so[s]["Длина"]) == "совпало"]
        if len(cands) == 1:
            pair(key, cands[0], "сечение+объём")
            out[-1]["Статус"] = "марка отличается"
        else:
            out.append({"Статус": "только в КЖ", "Режим": "", "МаркаКЖ": kz[key]["Марка"], "Сечение": key[1],
                        "КЖ_м": round(kz[key]["Длина"], 3), "СО_м": 0.0, "Разница": round(kz[key]["Длина"], 3),
                        "КлючСО": ""})
    for skey, g in so.items():
        if skey not in used:
            out.append({"Статус": "только в СО", "Режим": "", "МаркаКЖ": "", "Сечение": skey[1], "КЖ_м": 0.0,
                        "СО_м": round(g["Длина"], 3), "Разница": round(-g["Длина"], 3), "КлючСО": "|".join(skey)})
    return out
