"""Поиск комплектов с дублями номеров СО/ВОР и проверка сопоставления строк по словам.

Для каждой папки в РД/ с парой «спецификация + ВОР» (docx или doc, у doc берётся
копия из data/converted):
  1. находит дубли номеров в СО (колонка «Поз.») и в ВОР («№ п/п»);
  2. по ссылкам ВОР «...СО (поз. X)» находит группы, где в СО >1 строки с номером X;
  3. для строк ВОР из таких групп ищет пару в СО по словам: доля слов примечания СО,
     найденных в наименовании ВОР (числа обязаны совпасть). Объёмы не используются.

Запуск (из venv):  python -I -X utf8 scripts/find_dup_cases.py [РД] [data/converted] [отчёт.tsv]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.parsers.numbering_fix import numbering_fixed  # noqa: E402

THRESHOLD = 0.6   # минимальная доля слов для «частичной» пары
MARGIN = 0.2      # отрыв от второго варианта

TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")
REF_RE = re.compile(r"\.\s*СО\s*[(–—-]*\s*поз\.?\s*([^)\n;]*)", re.I)
NUM_RE = re.compile(r"\d+(?:\.\d+)*")


def norm(t):
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"-\s+", "", t)  # «Приме- чание»
    return re.sub(r"\s+", " ", t).strip()


def tokens(t):
    return [x.replace(",", ".") for x in TOKEN_RE.findall(norm(t))]


def is_vor(name):
    u = name.upper()
    return bool(re.search(r"(?<![СC])ВОР", u)) and "СОПОСТАВ" not in u


def is_so(name):
    u = name.upper()
    if any(x in u for x in ("СОПОСТАВ", "СОДЕРЖАН", "СВОР", "КАБЕЛЬН", "КАБ. ЖУРНАЛ", "ТИТУЛЬН")):
        return False
    return "СПЕЦИФИКАЦ" in u or bool(re.search(r"(?<![А-ЯA-Z])СО(?![А-ЯA-Z])", u))


def resolve(path, conv):
    """docx для файла: сам файл или копия из конвертации (по имени)."""
    if path.suffix.lower() == ".docx":
        return path
    cand = conv / (path.stem + ".docx")
    return cand if cand.exists() else None


def read_rows(path, kind):
    """kind='so' -> [(pos, name, note)], kind='vor' -> [(num, name, ref)]."""
    with numbering_fixed(str(path)) as fixed:
        d = docx.Document(fixed)
    out, mapping = [], None
    for tb in d.tables:
        rows = []
        for r in tb.rows:
            try:
                rows.append([c.text.strip() for c in r.cells])
            except Exception:
                rows.append([])
        start = 0
        for i, cells in enumerate(rows[:6]):
            h = [norm(c) for c in cells]
            if kind == "so":
                ok = any(x.startswith("поз") or x.startswith("№") for x in h) and any("наименование" in x for x in h)
            else:
                ok = any("№" in x for x in h) and any("наименование" in x for x in h)
            if ok:
                if kind == "so":
                    mapping = (
                        next(j for j, x in enumerate(h) if x.startswith("поз") or x.startswith("№")),
                        next(j for j, x in enumerate(h) if "наименование" in x),
                        next((j for j, x in enumerate(h) if "примечание" in x), None),
                        len(h),
                    )
                else:
                    mapping = (
                        next(j for j, x in enumerate(h) if "№" in x),
                        next(j for j, x in enumerate(h) if "наименование" in x),
                        next((j for j, x in enumerate(h) if "ссылка" in x), None),
                        len(h),
                    )
                start = i + 1
                break
        if mapping is None:
            continue
        for cells in rows[start:]:
            if len(cells) != mapping[3]:
                continue
            if re.fullmatch(r"\d{1,2}", cells[mapping[1]].strip()):
                continue  # строка нумерации колонок «1 2 3 ...»
            a, b = cells[mapping[0]], cells[mapping[1]]
            c = cells[mapping[2]] if (mapping[2] is not None and kind == "so") else " ".join(x for j, x in enumerate(cells) if j != mapping[1])
            out.append((a.strip().rstrip("."), b, c))
    # Первая строка блока с объединённой ячейкой номера приходит с пустым номером:
    # берём номер следующей строки, если у неё то же начало наименования.
    for i, (a, b, c) in enumerate(out[:-1]):
        n = out[i + 1]
        if not a and b and n[0] and norm(n[1])[:20] == norm(b)[:20]:
            out[i] = (n[0], b, c)
    return [r for r in out if r[0]]


def vor_refs(text):
    res = []
    for m in REF_RE.finditer(text or ""):
        res += NUM_RE.findall(m.group(1))
    return res


def match_group(vor_rows, so_rows):
    """Для каждой строки ВОР (name) -> (статус, индекс строки СО|None, оценка)."""
    # слова наименования и примечания СО: в группе с одним номером строки
    # различаются либо примечанием (зона), либо наименованием (вариант исполнения)
    so_tok = [set(tokens(n + " " + c)) for _, n, c in so_rows]
    if all(t == so_tok[0] for t in so_tok):
        return [("indistinct", None, 0.0) for _ in vor_rows]
    # слова, общие для всех строк группы, ничего не различают: оценивается только
    # то, чем строка отличается от остальных (зона, вариант исполнения)
    common = set.intersection(*so_tok)
    dist = [t - common for t in so_tok]
    res = []
    for _, vname, _ in vor_rows:
        vt = set(tokens(vname))
        scores = []
        for k, d in enumerate(dist):
            if not d:
                continue
            if not {x for x in d if x[0].isdigit()} <= vt:
                continue  # числа (зона 1.05, 120В) обязаны совпасть
            cov = len(d & vt) / len(d)
            if cov > 0:
                scores.append((cov, len(d), k))
        scores.sort(key=lambda x: (-x[0], -x[1]))
        if scores:
            top = scores[0]
            second = scores[1] if len(scores) > 1 else None
            if second and second[0] == top[0] and second[1] == top[1]:
                res.append(("ambiguous", None, top[0]))
            elif top[0] == 1.0:
                res.append(("exact", top[2], 1.0))
            elif top[0] >= THRESHOLD and top[0] - (second[0] if second else 0) >= MARGIN:
                res.append(("partial", top[2], top[0]))
            else:
                res.append(("none", None, top[0]))
            continue
        # ни одно отличительное слово не найдено: строка без отличий, если она одна
        empty = [k for k, d in enumerate(dist) if not d]
        if len(empty) == 1:
            res.append(("default", empty[0], 0.5))
        else:
            res.append(("none", None, 0.0))
    return res


def analyse(so_path, vor_path, conv):
    so = read_rows(so_path, "so")
    vor = read_rows(vor_path, "vor")
    so_by = defaultdict(list)
    for r in so:
        so_by[r[0]].append(r)
    vor_by = defaultdict(list)
    for r in vor:
        vor_by[r[0]].append(r)
    refs = defaultdict(list)
    for r in vor:
        for x in set(vor_refs(r[2])):
            refs[x].append(r)
    all_refs = set(refs)
    hit = len([x for x in all_refs if x in so_by])
    st = defaultdict(int)
    detail = []
    groups = 0
    for ref, vrows in refs.items():
        srows = so_by.get(ref, [])
        if len(srows) < 2:
            continue
        groups += 1
        if len(vrows) == 1:
            st["one_vor"] += 1
            continue
        mres = match_group(vrows, srows)
        used = defaultdict(int)
        for (s, k, sc), v in zip(mres, vrows):
            st[s] += 1
            if k is not None:
                used[k] += 1
            if s not in ("exact",):
                detail.append((ref, s, round(sc, 2), v[1][:80]))
        st["collision"] += sum(1 for n in used.values() if n > 1)
    return {
        "so_rows": len(so), "vor_rows": len(vor),
        "so_dup_nums": sum(1 for v in so_by.values() if len(v) > 1),
        "vor_dup_nums": sum(1 for v in vor_by.values() if len(v) > 1),
        "so_notes_empty": sum(1 for r in so if not r[2]),
        "refs": len(all_refs), "refs_in_so": hit,
        "multi_groups": groups, "stats": dict(st), "detail": detail,
    }


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "РД")
    conv = Path(sys.argv[2] if len(sys.argv) > 2 else "data/converted")
    report = Path(sys.argv[3]) if len(sys.argv) > 3 else None
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
    lines = ["папка\tСО\tВОР\tСО строк\tВОР строк\tдубли СО\tдубли ВОР\tпримечаний СО пусто\t"
             "ссылок ВОР\tиз них есть в СО\tгрупп СО>1 по ссылкам\tитоги пар"]
    found = []
    for d, g in sorted(by_dir.items()):
        for v in g["vor"]:
            vp = resolve(v, conv)
            if vp is None:
                print("нет docx:", v.name)
                continue
            best = None
            for s in g["so"]:
                sp = resolve(s, conv)
                if sp is None:
                    continue
                try:
                    a = analyse(sp, vp, conv)
                except Exception as e:  # noqa: BLE001
                    print("ошибка", s.name, v.name, e)
                    continue
                score = a["refs_in_so"]
                if best is None or score > best[0]:
                    best = (score, s, a)
            if best is None:
                continue
            _, s, a = best
            kit = str(d.relative_to(root))
            lines.append("\t".join(map(str, [
                kit, s.name, v.name, a["so_rows"], a["vor_rows"], a["so_dup_nums"], a["vor_dup_nums"],
                a["so_notes_empty"], a["refs"], a["refs_in_so"], a["multi_groups"], a["stats"]])))
            if a["multi_groups"]:
                found.append((kit, s.name, v.name, a))
    for kit, s, v, a in found:
        st = a["stats"]
        print(f"\n{kit}\n  СО: {s}\n  ВОР: {v}")
        print(f"  дубли номеров: СО {a['so_dup_nums']}, ВОР {a['vor_dup_nums']}; групп СО>1 по ссылкам: "
              f"{a['multi_groups']}; итоги: {st}")
        for ref, s2, sc, name in a["detail"][:6]:
            print(f"    {ref}\t{s2}\t{sc}\t{name}")
    print(f"\nпар СО+ВОР проверено: {len(lines) - 1}; с группами СО>1: {len(found)}")
    if report:
        report.write_text("\n".join(lines), encoding="utf-8")
        print("отчёт:", report)


if __name__ == "__main__":
    main()
