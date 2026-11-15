"""Цепочка изменений СВОР одного шифра: Изм.1 -> Изм.2 -> ...

Правило (проверено на ЭС1: 63 из 63 общих строк): П в Изм.N равно Р в Изм.N-1 (проектное количество после
предыдущего изменения). Р-П и «Откл» не используются; расхождение Откл с Р-П идёт в ошибки.
Строки соседних изменений сопоставляются по «раздел + наименование» (норм.), затем по наименованию без хвоста
«Наземная/Подземная часть» в том же разделе, если пара однозначна. Неоднозначное в пару не берётся.
Цвет только подтверждает статус по числам.

Ошибка: {"Шифр", "Изм", "Раздел", "Наименование", "Код", "Описание"}.
"""
import re
from collections import defaultdict
from pathlib import Path

from core.svor import status_by_numbers
from core.name_link import words
from core.svor_link import head, norm_name

EPS = 1e-6


def _eq(a, b):
    return abs((a or 0.0) - (b or 0.0)) <= EPS


def _err(code, izm, row, text, cipher=""):
    return {"Шифр": cipher, "Изм": izm, "Раздел": row.get("Раздел", ""), "Наименование": row.get("Наименование", ""),
            "Код": code, "Описание": text}


def _index(rows, keyf):
    d = defaultdict(list)
    for r in rows:
        d[(r["Раздел"], keyf(r["Наименование"]))].append(r)
    return d


def pair_rows(prev_rows, cur_rows):
    """[(строка_prev|None, строка_cur|None, режим)]. Режим: "имя", "имя без хвоста"."""
    pairs, used_p, used_c = [], set(), set()
    pk, ck = _index(prev_rows, norm_name), _index(cur_rows, norm_name)
    for k, cs in ck.items():
        ps = pk.get(k, [])
        for p, c in zip(ps, cs):  # дубли ключа - по порядку появления
            pairs.append((p, c, "имя"))
            used_p.add(id(p))
            used_c.add(id(c))
    rest_p = [r for r in prev_rows if id(r) not in used_p]
    rest_c = [r for r in cur_rows if id(r) not in used_c]
    pk2 = _index(rest_p, lambda n: norm_name(head(n)))
    ck2 = _index(rest_c, lambda n: norm_name(head(n)))
    for k, cs in ck2.items():
        ps = pk2.get(k, [])
        if len(ps) == 1 and len(cs) == 1:
            pairs.append((ps[0], cs[0], "имя без хвоста"))
            used_p.add(id(ps[0]))
            used_c.add(id(cs[0]))
    # наименование переписано: тот же раздел и единица, П(cur) = Р(prev), общие слова >= половины; пара должна быть единственной
    rest_p = [r for r in prev_rows if id(r) not in used_p]
    rest_c = [r for r in cur_rows if id(r) not in used_c]
    cand = []
    for c in rest_c:
        wc = set(words(c["Наименование"]))
        for p in rest_p:
            if p["Раздел"] != c["Раздел"] or not p["Р"] or not _eq(c["П"], p["Р"]):
                continue
            if norm_name(p["Ед"]) != norm_name(c["Ед"]):
                continue
            wp = set(words(p["Наименование"]))
            score = len(wc & wp) / max(1, len(wc | wp))
            if score >= 0.5:
                cand.append((p, c))
    for p, c in cand:
        if sum(1 for x, _ in cand if x is p) == 1 and sum(1 for _, y in cand if y is c) == 1:
            pairs.append((p, c, "слова и число"))
            used_p.add(id(p))
            used_c.add(id(c))
    pairs += [(r, None, "") for r in prev_rows if id(r) not in used_p]
    pairs += [(None, r, "") for r in cur_rows if id(r) not in used_c]
    return pairs


def check_chain(izms, cipher=""):
    """izms: {номер_изменения: [строки read_svor]}. Возвращает (цепочка, ошибки).

    цепочка: по строке на позицию: {"Шифр", "Раздел", "Наименование", "Ед", "Изм N П", "Изм N Р", ...}.
    """
    errors, chain = [], []
    nums = sorted(izms)
    for a, b in zip(nums, nums[1:]):
        if b - a > 1:
            errors.append(_err("нет_изменения", b, {}, "между Изм.%d и Изм.%d нет файла СВОР" % (a, b), cipher))
    for n in nums:
        # повтор имени в разделе - норма (70%/30% грунта и т.п.), пары берутся по порядку, не ошибка
        for r in izms[n]:
            if r["Откл"] is not None and r["П"] is not None and r["Р"] is not None \
                    and not _eq(r["Р"] - r["П"], r["Откл"]):
                errors.append(_err("откл_не_равно_Р-П", n, r, "Откл %s, Р-П %s" % (r["Откл"], r["Р"] - r["П"]), cipher))
            c, s = r["Цвет"], status_by_numbers(r["П"], r["Р"])
            if c == "зелёный" and s not in ("новая", ""):
                errors.append(_err("цвет", n, r, "зелёный, по числам %s" % s, cipher))
            if c == "красный" and s == "без изменений" and r["Откл"]:
                errors.append(_err("цвет", n, r, "красный, но П=Р", cipher))
    index = {}  # ключ позиции -> запись цепочки
    first = nums[0] if nums else None
    for r in (izms[first] if first is not None else []):
        rec = {"Шифр": cipher, "Раздел": r["Раздел"], "Наименование": r["Наименование"], "Ед": r["Ед"]}
        rec["Изм %d П" % first], rec["Изм %d Р" % first] = r["П"], r["Р"]
        chain.append(rec)
        index[id(r)] = rec
    for a, b in zip(nums, nums[1:]):
        if b - a != 1:
            continue
        for p, c, mode in pair_rows(izms[a], izms[b]):
            if c is None:
                if not _eq(p["Р"], 0):
                    errors.append(_err("пропала", b, p, "в Изм.%d Р=%s, в Изм.%d строки нет и нет пометки «удалена»"
                                       % (a, p["Р"], b), cipher))
                continue
            if p is None:
                rec = {"Шифр": cipher, "Раздел": c["Раздел"], "Наименование": c["Наименование"], "Ед": c["Ед"]}
                chain.append(rec)
                if not _eq(c["П"], 0):
                    errors.append(_err("нет_предшественника", b, c,
                                       "П=%s, а в Изм.%d такой строки нет (новая строка должна иметь П=0)" % (c["П"], a), cipher))
            else:
                rec = index.get(id(p))
                if rec is None:
                    continue
                if not _eq(c["П"], p["Р"]):
                    errors.append(_err("цепочка", b, c, "П=%s, а Р в Изм.%d равно %s" % (c["П"], a, p["Р"]), cipher))
                if mode != "имя":
                    errors.append(_err("имя_изменилось", b, c, "связано по «%s» с «%s»" % (mode, p["Наименование"][:60]), cipher))
                if c["Ед"] != p["Ед"] and norm_name(c["Ед"]) != norm_name(p["Ед"]):
                    errors.append(_err("единица", b, c, "было «%s», стало «%s»" % (p["Ед"], c["Ед"]), cipher))
            rec["Изм %d П" % b], rec["Изм %d Р" % b] = c["П"], c["Р"]
            rec["Изм %d Статус" % b] = status_by_numbers(c["П"], c["Р"])
            index[id(c)] = rec
    return chain, errors


_IZM = re.compile(r"ИЗМ\s*(\d+)", re.IGNORECASE)
_CIPHER = re.compile(r"(ЕСТ-ПМ-\d+-Р-\d+-[^\\/]+)")


def find_svor(root):
    """{шифр: {изм: [пути]}} по папкам вида РД/<шифр>/ИЗМN .../*СВОР*.docx."""
    out = defaultdict(lambda: defaultdict(list))
    for p in sorted(Path(root).rglob("*СВОР*.docx")):
        if p.name.startswith("~$"):
            continue
        s = str(p)
        m, c = _IZM.search(s), _CIPHER.search(s)
        if not (m and c):
            continue
        out[c.group(1)][int(m.group(1))].append(p)
    return out


def run(root, read=None):
    """Для каждого шифра с несколькими изменениями: (цепочка, ошибки). Шифры с одним изменением - только проверки строк."""
    if read is None:
        from core.svor import read_svor as read
    result = {}
    for cipher, by_izm in find_svor(root).items():
        izms, errs = {}, []
        for n, paths in by_izm.items():
            izms[n] = read(paths[0])
            if len(paths) > 1:
                errs.append({"Шифр": cipher, "Изм": n, "Раздел": "", "Наименование": paths[1].name, "Код": "несколько_файлов",
                             "Описание": "в Изм.%d несколько СВОР, взят %s" % (n, paths[0].name)})
        chain, e = check_chain(izms, cipher)
        result[cipher] = (chain, errs + e)
    return result
