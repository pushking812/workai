"""Поиск комплектов, где правка склейки СО (метка в примечании входит в ключ, ФайлBinary.pq) меняет число строк.

Для каждого СО в РД/ (docx, у doc берётся копия из data/converted) считает по паре (номер, наименование):
  до правки  - все повторы склеивались в одну строку;
  после      - повторы с разной меткой (наземн/подземн/зона/этаж/секци/часть) остаются отдельно.
Метки должны совпадать со списком `метки` в PQ/СО/запросы/ФайлBinary.pq.
Выводит комплекты, где число строк изменилось, и примеры примечаний (чтобы увидеть ложные метки).
Это приближение: настоящая склейка учитывает ещё все прочие поля строки.

Запуск (из venv):  python -I -X utf8 scripts/find_label_collapse.py [РД] [data/converted] [отчёт.tsv] [подстрока пути]
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_dup_cases import is_so, is_vor, norm, read_rows, resolve  # noqa: E402

LABELS = ("наземн", "подземн", "зона", "зоне", "этаж", "секци", "часть")


def label_of(note):
    n = (note or "").strip().lower()
    return n if n and any(x in n for x in LABELS) else ""


def analyse(so_path):
    rows = read_rows(so_path, "so")
    groups = defaultdict(list)
    for pos, name, note in rows:
        groups[(pos, norm(name))].append(note)
    before = len(groups)
    after = 0
    examples = []
    for (pos, name), notes in groups.items():
        keys = {label_of(n) for n in notes}
        after += len(keys)
        if len(keys) > 1:
            examples.append((pos, name[:40], sorted(k[:50] for k in keys)))
    return {"rows": len(rows), "before": before, "after": after, "examples": examples}


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "РД")
    conv = Path(sys.argv[2] if len(sys.argv) > 2 else "data/converted")
    report = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    flt = sys.argv[4] if len(sys.argv) > 4 else ""
    lines = ["папка\tСО\tстрок\tгрупп до\tгрупп после\tприрост"]
    changed = 0
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".doc", ".docx") or p.name.startswith("~$"):
            continue
        if "Обосновывающие" in str(p) or is_vor(p.name) or not is_so(p.name) or flt not in str(p):
            continue
        sp = resolve(p, conv)
        if sp is None:
            print("нет docx:", p.name)
            continue
        try:
            a = analyse(sp)
        except Exception as e:  # noqa: BLE001
            print("ошибка", p.name, e)
            continue
        total += 1
        kit = str(p.parent.relative_to(root))
        d = a["after"] - a["before"]
        lines.append("\t".join(map(str, [kit, p.name, a["rows"], a["before"], a["after"], d])))
        if d:
            changed += 1
            print(f"\n{kit}\n  {p.name}: строк {a['rows']}, групп {a['before']} -> {a['after']} (+{d})")
            for ex in a["examples"][:4]:
                print("   ", ex)
        sys.stdout.flush()
    print(f"\nСО проверено: {total}; с изменением: {changed}")
    if report:
        report.write_text("\n".join(lines), encoding="utf-8")
        print("отчёт:", report)


if __name__ == "__main__":
    main()
