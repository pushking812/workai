"""Сверка core/name_link.py с запросами PQ: СвязьПоИмени и «ссылка, вероятно, сдвинута» на листе Ошибки.

Вход: каталог с выгрузками pq_eval.ps1 (UTF-16, табуляция) и метка комплекта; файлы вида
  <каталог>/ev_<метка>_<запрос>.txt для запросов ВОР_Строки, СО_Строки, ВОР_СвязьСО, Связь_ВОР_СО, СвязьПоИмени, Ошибки.

Запуск (из venv):  python -I -X utf8 scripts/compare_name_link.py <каталог> <метка> [<метка> ...]
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.name_link import name_match, shift_hints  # noqa: E402


def load(d, label, query):
    with open(Path(d) / f"ev_{label}_{query}.txt", encoding="utf-16", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def compare(d, label):
    vor = load(d, label, "ВОР_Строки")
    so = load(d, label, "СО_Строки")
    links = load(d, label, "ВОР_СвязьСО")
    full = load(d, label, "Связь_ВОР_СО")
    pq_name = load(d, label, "СвязьПоИмени")
    pq_err = [r for r in load(d, label, "Ошибки") if r["ТипПроблемы"] == "ссылка, вероятно, сдвинута"]

    bad = []
    py = name_match(vor, so, links)
    a = {(r["Статус"], r["ИдСтроки"], r["КлючСО"], r["NППСО"], str(r["СтрокСО"]), r["Номера"]) for r in py}
    b = {(r["Статус"], r["ИдСтроки"], r["КлючСО"], r["NППСО"], r["СтрокСО"], r["Номера"]) for r in pq_name}
    bad += [("СвязьПоИмени только в Python", x) for x in sorted(a - b)]
    bad += [("СвязьПоИмени только в PQ", x) for x in sorted(b - a)]

    sh = shift_hints(full, so)
    a2 = {(r["NПП"], r["КлючСО"]) for r in sh}
    b2 = {(r["NПП"], r["КлючСО"]) for r in pq_err}
    bad += [("сдвиг только в Python", x) for x in sorted(a2 - b2)]
    bad += [("сдвиг только в PQ", x) for x in sorted(b2 - a2)]

    print(f"{label}: по наименованию {len(py)} (PQ {len(pq_name)}), сдвиг {len(sh)} (PQ {len(pq_err)}), расхождений {len(bad)}")
    for x in bad[:20]:
        print("  ", x)
    return len(bad)


if __name__ == "__main__":
    d = sys.argv[1]
    sys.exit(1 if sum(compare(d, m) for m in sys.argv[2:]) else 0)
