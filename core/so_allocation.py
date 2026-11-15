"""Единое правило распределения объёма СО по строкам ВОР (эталон на Python для запроса Связь_ВОР_СО.pq).

Группа = все строки ВОР, ссылающиеся на один КлючСО, и все строки СО с этим ключом.
Объём каждой строки СО распределяется по строкам ВОР ровно один раз (сумма долей строки СО = 1).
Вход: вор = [{name, ed, kol}], со = [{name, ed, kol, note}].
Выход: (доли, замечания): доли = [(i_вор, j_со, доля)], замечания = [(код, i_вор|None, j_со|None)].

Порядок (одинаков для любых пунктов, списка слов «наземная/подземная» нет):
  1. Слова: нижний регистр, ё->е, разделители -> пробел, кириллическая «х» между цифрами -> x; слово без цифр короче
     3 знаков выброшено и сравнивается по первым 5 знакам (наземная/наземной), слово с цифрой целиком.
     «надземная» считается синонимом «наземная».
  2. Совместимость: все слова с цифрами из наименования+примечания СО обязаны быть в наименовании ВОР
     (1x2x1,78 не подходит к 1x2x1,5). Если так отсеяны все строки ВОР, проверка отключается (замечание).
  3. Оценка пары = доля «отличительных» слов строки СО (не общих для всех строк СО группы), найденных в ВОР.
  4. Строка ВОР, у которой для другой строки СО оценка строго выше, уступает ей (занята): так «Монтаж»/«Демонтаж»
     и «наземная часть»/«Зоны 2.01-2.05» разводятся без общих слов. Если после этого кандидатов нет - уступка отменяется.
  5. Лучшие кандидаты строки СО; среди них оставляются строки ВОР с той же единицей, что у СО (если такие есть).
  6. Нет строки ВОР в единице СО - объём СО (для итога) получает первая, замечание «единицы разные».
     Один кандидат - вся доля ему. Несколько (одна единица, допуск TOL = 0,5%):
       - один раздел ВОР и каждая КолВо = СО: «операция» (первая строка учтена, остальные доля 0, справочно полный объём СО);
       - один раздел ВОР и сумма КолВо = СО: деление пропорционально КолВо;
       - ровно одна КолВо = СО: ей всё («по объёму»);
       - иначе первой строке и замечание «проверить вручную».
  7. Строка ВОР без доли остаётся в связи с долей 0: «нет аналога: другая единица» или «ВОР без доли СО».
Объёмы ВОР и СО на выбор пары не влияют, они определяют только режим учёта (п. 6). Ключ vor[i]["section"] - раздел.
"""
import re

SEPARATORS = "/,();:-–—«»\"' \n\r\t=+*[]|#"
SYNONYMS = {"надзе": "назем"}


def _norm(text):
    s = (text or "").lower().replace("ё", "е")
    s = re.sub(r"(?<=\d)[х×](?=\d)", "x", s)
    for d in SEPARATORS:
        s = s.replace(d, " ")
    return s


def words(text):
    out = []
    for w in _norm(text).split(" "):
        w = w.strip(".")
        if not w:
            continue
        if re.search(r"\d", w):
            out.append(w)
        elif len(w) >= 3:
            w = w[:5]
            out.append(SYNONYMS.get(w, w))
    return list(dict.fromkeys(out))


def _unit(x):
    return (x or "").replace(".", "").strip().lower()


TOL = 0.005  # допуск «примерно равно» (анализ по РД/: расхождений между 0 и 7,5% нет, годится 0,1..4%)


def _eq(a, b):
    return a is not None and b not in (None, 0) and abs(a - b) / abs(b) <= TOL


def allocate(vor, so):
    shares, notes, _ = allocate_detail(vor, so)
    return [(i, j, s) for i, j, s, *_ in shares], notes


def allocate_detail(vor, so):
    """То же, что allocate, но с видом каждой пары: ([(i, j, доля, вид, оценка)], замечания, сведения).

    вид: один, единицы, операция, доля, объём, вручную, без. Сведения: статус, сравнимо, справочно по паре (i, j)
    (зеркало СтатусПары, Сравнимо и СО_Справочно запроса Связь_ВОР_СО.pq).
    """
    nv, ns = len(vor), len(so)
    notes = []
    kinds = {}
    no_num = set()
    vw = [set(words(v["name"])) for v in vor]
    sw = [set(words(s["name"] + " " + s.get("note", ""))) for s in so]
    common = set.intersection(*sw) if sw else set()
    dist = [t - common for t in sw]

    def compatible(strict):
        res = [[True] * ns for _ in range(nv)]
        if strict:
            for i in range(nv):
                for j in range(ns):
                    res[i][j] = {w for w in sw[j] if re.search(r"\d", w)} <= vw[i]
        return res

    comp = compatible(True)
    for j in range(ns):
        if not any(comp[i][j] for i in range(nv)):
            for i in range(nv):
                comp[i][j] = True
            notes.append(("числа не совпали", None, j))
            no_num.add(j)

    def score(i, j):
        d = dist[j]
        return len(d & vw[i]) / len(d) if d else 0.0

    sc = [[score(i, j) if comp[i][j] else -1.0 for j in range(ns)] for i in range(nv)]
    best_of_v = [max(sc[i]) if ns else -1.0 for i in range(nv)]

    shares = {}
    for j in range(ns):
        cand = [i for i in range(nv) if comp[i][j]]
        if not cand:
            continue
        top = max(sc[i][j] for i in cand)
        cand = [i for i in cand if sc[i][j] == top]
        free = [i for i in cand if sc[i][j] >= best_of_v[i]]
        if free:
            cand = free
        same = [i for i in cand if _unit(vor[i]["ed"]) == _unit(so[j]["ed"])]
        if not same:
            # единицы ВОР и СО разные: сравнивать объёмы нельзя; объём СО (для итога) получает первая строка
            shares[(cand[0], j)] = 1.0
            kinds[(cand[0], j)] = "единицы"
            notes.append(("единицы разные", cand[0], j))
            continue
        cand = same
        if len(cand) == 1:
            shares[(cand[0], j)] = 1.0
            kinds[(cand[0], j)] = "один"
            continue
        kols = [vor[i].get("kol") for i in cand]
        sk = so[j].get("kol")
        one_section = len({vor[i].get("section") for i in cand}) == 1
        have = sk and sk > 0 and all(k and k > 0 for k in kols)
        if have and one_section and all(_eq(k, sk) for k in kols):
            # операции над одним материалом: объём СО учтён один раз (первая строка), остальным справочно
            shares[(cand[0], j)] = 1.0
            kinds[(cand[0], j)] = "операция"
            for i in cand[1:]:
                shares[(i, j)] = 0.0
                kinds[(i, j)] = "операция"
                notes.append(("операция", i, j))
        elif have and one_section and _eq(sum(kols), sk):
            tot = sum(kols)
            for i, k in zip(cand, kols):
                shares[(i, j)] = k / tot
                kinds[(i, j)] = "доля"
            notes.append(("доля по КолВо", None, j))
        elif have and sum(_eq(k, sk) for k in kols) == 1:
            win = cand[[_eq(k, sk) for k in kols].index(True)]
            shares[(win, j)] = 1.0
            kinds[(win, j)] = "объём"
            notes.append(("по объёму", win, j))
        else:
            shares[(cand[0], j)] = 1.0
            kinds[(cand[0], j)] = "вручную"
            notes.append(("проверить вручную", cand[0], j))
    got = {i for i, _ in shares}
    for i in range(nv):
        if i not in got and ns:
            j = max(range(ns), key=lambda k: sc[i][k])
            shares[(i, j)] = 0.0
            kinds[(i, j)] = "без"
            diff = _unit(vor[i]["ed"]) != _unit(so[j]["ed"])
            notes.append(("нет аналога: другая единица" if diff else "ВОР без доли СО", i, j))

    def status(i, j, share, kind):
        if kind == "операция":
            return "операция над тем же материалом"
        if kind == "без" and _unit(vor[i]["ed"]) != _unit(so[j]["ed"]):
            return "нет аналога (другая единица)"
        if share == 0:
            return "ВОР без доли"
        if ns == 1 and (nv == 1 or kind == "один"):
            return "единственная"
        if ns > 1 and not dist[j]:
            return "дубль в СО"
        for k, text in (("доля", "доля по КолВо"), ("единицы", "единицы разные"),
                        ("объём", "по объёму"), ("вручную", "проверить вручную")):
            if kind == k:
                return text
        if sc[i][j] >= 1:
            return "точно"
        if j in no_num:
            return "числа не совпали"
        return "нечётко" if sc[i][j] > 0 else "по остатку"

    out, info = [], {}
    for (i, j), s in sorted(shares.items()):
        kind = kinds[(i, j)]
        score_ = None if (not dist[j] or sc[i][j] < 0) else sc[i][j]
        out.append((i, j, s, kind, score_))
        info[(i, j)] = {"status": status(i, j, s, kind), "score": score_, "comparable": 0 if kind == "без" else 1,
                        "ref": so[j].get("kol") if kind == "операция" else None}
    return out, notes, info
