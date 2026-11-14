"""Сопоставление «только в ВОР» и «только в СО» по наименованию (зеркало запроса Сопоставление_по_названию.pq).

Правило (то же, что в запросе):
  слова = нижний регистр, ё->е, разделители -> пробел, точки по краям убраны, слова без цифр короче 3 знаков выброшены;
  слово без цифр сравнивается по первым 5 знакам (хомут/хомуты), слово с цифрой - целиком;
  пара кандидатов (строка ВОР, строка СО) в одном шифре и номере изменения (дата не учитывается):
    в наименовании СО не меньше двух слов, все они есть в наименовании ВОР, оценка = число слов наименования СО (длиннее - надёжнее),
    бонус = число слов без цифр из примечания СО, найденных в ВОР;
  пара ставится, если она единственная лучшая и для строки ВОР, и для строки СО (взаимно), иначе - неоднозначно.

Запуск: python -I -X utf8 scripts/check_name_match.py <книга ВОР+СО.xlsx> [...]
"""
import re
import sys

import openpyxl

SEP = "/,();:-–—«»\"' \n\r\t=+*[]|"


def words(text):
    s = (text or "").lower().replace("ё", "е")
    for d in SEP:
        s = s.replace(d, " ")
    out = []
    for w in s.split(" "):
        w = w.strip(".")
        if len(w) >= 3 or re.search(r"\d", w):
            out.append(w if re.search(r"\d", w) else w[:5])
    return list(dict.fromkeys(out))


def rows(ws):
    it = ws.iter_rows(values_only=True)
    head = next(it)
    return [dict(zip(head, r)) for r in it]


def match(vor_rows, so_rows):
    cand = []  # (i, j, score, bonus)
    for i, v in enumerate(vor_rows):
        vw = set(words(v["НаименованиеРабот"]))
        for j, s in enumerate(so_rows):
            if (v["ШифрПроекта"], v["НомИзмПроекта"]) != (s["ШифрПроекта"], s["НомИзмПроекта"]):
                continue
            nw = words(s["НаименованиеИТехХар"])
            if len(nw) < 2 or not set(nw) <= vw:
                continue
            bonus = sum(1 for w in words(s["Примечание"]) if not re.search(r"\d", w) and w in vw)
            sec = len(set(w for w in words(s.get("Раздел")) if not re.search(r"\d", w))
                      & set(words(v.get("Раздел"))))
            cand.append((i, j, (len(nw), min(bonus, 999), min(sec, 999)), 0))
    res = []
    for i, j, sc, _ in cand:
        key = sc
        best_v = max(c[2] for c in cand if c[0] == i)
        best_s = max(c[2] for c in cand if c[1] == j)
        n_v = sum(1 for c in cand if c[0] == i and c[2] == best_v)
        n_s = sum(1 for c in cand if c[1] == j and c[2] == best_s)
        if key == best_v and key == best_s and n_v == 1 and n_s == 1:
            res.append((i, j, "по наименованию"))
        elif key == best_v or key == best_s:
            res.append((i, j, "неоднозначно"))
    return res


def main(paths):
    for p in paths:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        v = rows(wb["Только_в_ВОР"])
        s = rows(wb["Только_в_СО"])
        print("==", p, "ВОР", len(v), "СО", len(s))
        for i, j, st in match(v, s):
            print(" ", st, "| ВОР", v[i]["NПП"], v[i]["НаименованиеРабот"][:60], "<->",
                  "СО", s[j]["NПП"], s[j]["НаименованиеИТехХар"][:50])


if __name__ == "__main__":
    main(sys.argv[1:])
