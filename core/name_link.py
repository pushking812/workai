"""Эталон на Python: связь по наименованию и подсказка «ссылка, вероятно, сдвинута».

Зеркало PQ/ВОР+СО/запросы/СвязьПоИмени.pq и блока 7 запроса Ошибки.pq. Правка правила - в обоих местах.
Сверка с Excel: scripts/compare_name_link.py.

Строки - словари с именами столбцов запросов PQ (ВОР_Строки, СО_Строки, ВОР_СвязьСО, Связь_ВОР_СО).
"""
import re

_SEP = ["/", ",", "(", ")", ";", ":", "-", "–", "—", "«", "»", '"', "'", "\xa0", "\n", "\r", "\t", "=", "+", "*", "[", "]", "|", " "]
_DIGIT = re.compile(r"[0-9]")


def _t(x):
    return "" if x is None else str(x)


def has_digit(w):
    return bool(_DIGIT.search(w))


def words(text):
    """Слова наименования: нижний регистр, ё->е, слова без цифр короче 3 знаков выброшены,
    слово без цифр - первые 5 знаков, слово с цифрой - целиком; без повторов, порядок сохранён."""
    s = _t(text).lower().replace("ё", "е")
    for d in _SEP:
        s = s.replace(d, " ")
    out = []
    for w in s.split(" "):
        w = w.strip(".")
        if len(w) >= 3 or has_digit(w):
            out.append(w if has_digit(w) else w[:5])
    return list(dict.fromkeys(out))


def fits(so_words, vor_words):
    """Все слова наименования СО (не меньше двух) есть в наименовании ВОР."""
    return len(so_words) >= 2 and set(so_words) <= set(vor_words)


def _best(cands):
    """cands: [(i, j, k)] -> [(i, j, k, ok_vor_unique_best, ok_so_unique_best)]"""
    by_v, by_s = {}, {}
    for i, j, k in cands:
        by_v.setdefault(i, []).append(k)
        by_s.setdefault(j, []).append(k)
    mv = {i: (max(ks), ks.count(max(ks))) for i, ks in by_v.items()}
    ms = {j: (max(ks), ks.count(max(ks))) for j, ks in by_s.items()}
    out = []
    for i, j, k in cands:
        out.append((i, j, k, mv[i], ms[j]))
    return out


def _so_id(r):
    return "#".join((_t(r.get("КлючСО")), _t(r.get("ИмяФайла")), _t(r.get("Таблица")), _t(r.get("Строка"))))


def name_match(vor_rows, so_rows, links):
    """Связь по наименованию для строк, не связанных по номеру (СвязьПоИмени.pq).

    vor_rows - ВОР_Строки, so_rows - СО_Строки, links - ВОР_СвязьСО (нужны ИдСтроки и КлючСО).
    Возвращает список записей: Статус «по наименованию» (одна на пару) или «неоднозначно» (одна на строку ВОР).
    """
    so_keys = {_t(r["КлючСО"]) for r in so_rows}
    linked_ids = {_t(l["ИдСтроки"]) for l in links}
    linked_keys = {_t(l["КлючСО"]) for l in links}
    lost = {_t(l["ИдСтроки"]) for l in links if _t(l["КлючСО"]) not in so_keys}
    vor_ids = lost | {_t(v["ИдСтроки"]) for v in vor_rows if _t(v["ИдСтроки"]) not in linked_ids}
    vo = [v for v in vor_rows if _t(v["ИдСтроки"]) in vor_ids]
    so = [s for s in so_rows if _t(s["КлючСО"]) not in linked_keys]

    vw = [words(v["НаименованиеРабот"]) for v in vo]
    sw = [words(s["НаименованиеИТехХар"]) for s in so]
    sprim = [[w for w in words(s.get("Примечание")) if not has_digit(w)] for s in so]
    vsec = [words(v.get("Раздел")) for v in vo]
    ssec = [[w for w in words(s.get("Раздел")) if not has_digit(w)] for s in so]

    cands = []
    for i, v in enumerate(vo):
        for j, s in enumerate(so):
            if v["ШифрПроекта"] != s["ШифрПроекта"] or v["НомИзмПроекта"] != s["НомИзмПроекта"]:
                continue
            if not fits(sw[j], vw[i]):
                continue
            k = (len(sw[j]) * 1000000
                 + min(len(set(sprim[j]) & set(vw[i])), 999) * 1000
                 + min(len(set(ssec[j]) & set(vsec[i])), 999))
            cands.append((i, j, k))

    exact, amb = [], {}
    for i, j, k, (mv, nv), (ms, ns) in _best(cands):
        if k == mv and k == ms and nv == 1 and ns == 1:
            exact.append((i, j))
        elif k == mv or k == ms:
            amb.setdefault(i, []).append(j)

    res = []
    for i, j in exact:
        v, s = vo[i], so[j]
        res.append({"Статус": "по наименованию", "ИдСтроки": v["ИдСтроки"], "NПП": v["NПП"],
                    "NППСО": s["NПП"], "КлючСО": s["КлючСО"], "СтрокСО": 1, "Номера": _t(s["NПП"])})
    for i, js in amb.items():
        js = sorted(js)
        v, s = vo[i], so[js[0]]
        res.append({"Статус": "неоднозначно", "ИдСтроки": v["ИдСтроки"], "NПП": v["NПП"],
                    "NППСО": s["NПП"], "КлючСО": s["КлючСО"], "СтрокСО": len(js),
                    "Номера": ", ".join(_t(so[x]["NПП"]) for x in js[:5])})
    return res


def shift_hints(link_rows, so_rows):
    """Подсказки «ссылка, вероятно, сдвинута» (блок 7 в Ошибки.pq).

    link_rows - Связь_ВОР_СО (34 столбца), so_rows - СО_Строки.
    Строка ВОР не подтверждена, если ни у одной связанной строки СО все слова не входят в её наименование;
    строка СО не подтверждена, если её не подтверждает ни одна связанная ВОР. Пара берётся, если она единственная
    лучшая и для ВОР, и для СО (оценка = число слов СО), шифр и номер изменения равны.
    """
    seen = set()
    vor_info = {}      # ИдСтроки -> запись ВОР (первая)
    vor_ok = {}        # ИдСтроки -> подтверждена
    vor_refs = {}      # ИдСтроки -> номера пунктов СО
    so_ok = set()
    for r in link_rows:
        sid = "#".join((_t(r["КлючСО"]), _t(r["СО_ИмяФайла"]), _t(r["СО_Таблица"]), _t(r["СО_Строка"])))
        tag = (r["ИдСтроки"], sid, _t(r["NППСО"]))
        if tag in seen:
            continue
        seen.add(tag)
        ok = fits(words(r["СО_НаименованиеИТехХар"]), words(r["НаименованиеРабот"]))
        vor_info.setdefault(r["ИдСтроки"], r)
        vor_ok[r["ИдСтроки"]] = vor_ok.get(r["ИдСтроки"], False) or ok
        refs = vor_refs.setdefault(r["ИдСтроки"], [])
        if _t(r["NППСО"]) not in refs:
            refs.append(_t(r["NППСО"]))
        if ok:
            so_ok.add(sid)

    vo = [vor_info[i] for i in vor_info if not vor_ok[i]]
    so = [s for s in so_rows if _so_id(s) not in so_ok]
    vw = [words(v["НаименованиеРабот"]) for v in vo]
    sw = [words(s["НаименованиеИТехХар"]) for s in so]
    cands = []
    for i, v in enumerate(vo):
        for j, s in enumerate(so):
            if v["ШифрПроекта"] == s["ШифрПроекта"] and v["НомИзмПроекта"] == s["НомИзмПроекта"] and fits(sw[j], vw[i]):
                cands.append((i, j, len(sw[j])))
    res = []
    for i, j, k, (mv, nv), (ms, ns) in _best(cands):
        if k == mv and k == ms and nv == 1 and ns == 1:
            v, s = vo[i], so[j]
            res.append({"ИдСтроки": v["ИдСтроки"], "NПП": _t(v["NПП"]), "КлючСО": s["КлючСО"], "NППСО": _t(s["NПП"]),
                        "Ссылки": ", ".join(vor_refs[v["ИдСтроки"]])})
    return res
