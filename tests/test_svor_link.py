from pathlib import Path

import pytest

from core import svor_link as sl

ROOT = Path(__file__).resolve().parent.parent


def S(name, unit, p, r):
    return {"Наименование": name, "Ед": unit, "П": p, "Р": r}


def V(name, unit, qty):
    return {"Наименование": name, "Ед": unit, "Кол": qty, "Номер": "1", "Шифр": "А"}


def test_head_cuts_part_tail():
    assert sl.head("Кроссировка в шкафу Наземная часть выше отм.0,000 – 540 шт.") == "Кроссировка в шкафу"
    assert sl.head("Монтаж шкафа") == "Монтаж шкафа"


def test_exact_name_match_and_unit_matters():
    r = sl.link([S("Монтаж шкафа", "шт.", 0, 2), S("Прокладка кабеля", "м", 5, 10)],
                [V("Монтаж  Шкафа", "шт", "2"), V("Прокладка кабеля", "шт.", "10")])
    st = sorted((x["Статус"], x["Режим"]) for x in r)
    # другая единица - не пара
    assert ("совпало", "имя") in st and ("только в СВОР", "") in st and ("только в ВОР", "") in st


def test_quantities_summed_and_tolerance():
    r = sl.link([S("Монтаж", "шт.", 0, 3), S("Монтаж", "шт.", 0, 2)], [V("Монтаж", "шт.", "5,02")])
    assert r[0]["Статус"] == "совпало" and r[0]["СтрокСВОР"] == 2
    r = sl.link([S("Монтаж", "шт.", 0, 5)], [V("Монтаж", "шт.", "7")])
    assert r[0]["Статус"] == "ВОР больше" and r[0]["Разница"] == -2
    r = sl.link([S("Монтаж", "шт.", 0, 9)], [V("Монтаж", "шт.", "7")])
    assert r[0]["Статус"] == "СВОР больше" and r[0]["Разница"] == 2


def test_tail_mode_sums_by_head():
    r = sl.link([S("Кроссировка Наземная часть выше отм.0,000 – 540 шт.", "шт.", 0, 360)],
                [V("Кроссировка Наземная часть выше отм.0,000 – 180 шт.", "шт.", "180"),
                 V("Кроссировка Наземная часть ниже отм.0,000 – 180 шт.", "шт.", "180")])
    assert len(r) == 1 and r[0]["Режим"] == "имя без хвоста" and r[0]["Статус"] == "совпало"


def test_deleted_svor_rows_are_not_searched_in_vor():
    r = sl.link([S("Монтаж шкафа", "шт.", 3, 0)], [])
    assert [x["Статус"] for x in r] == ["удалена в СВОР"]


def test_words_mode_needs_single_candidate():
    s = [S("Монтаж блока питания 24В 5А", "шт.", 0, 2)]
    one = sl.link(s, [V("Монтаж блока 24В питания 5А", "шт.", "2")])
    assert one[0]["Режим"] == "слова" and one[0]["Статус"] == "совпало"
    two = sl.link(s, [V("Монтаж блока 24В питания 5А", "шт.", "2"), V("Монтаж 24В блока питания 5А", "шт.", "2")])
    # два кандидата с теми же словами - не угадываем
    assert sorted(x["Статус"] for x in two) == ["только в ВОР", "только в ВОР", "только в СВОР"]
    # одинаковые по имени строки ВОР суммируются: 2 + 2 против 2
    same = sl.link(s[:0] + [S("Монтаж", "шт.", 0, 2)], [V("Монтаж", "шт.", "2"), V("Монтаж", "шт.", "2")])
    assert same[0]["Статус"] == "ВОР больше" and same[0]["СтрокВОР"] == 2


def test_vor_rows_from_strings_filters_like_pq_query():
    rows = [{"ИдСтроки": "1", "НаименованиеРабот": "Монтаж", "ЕдИзм": "шт.", "КолВо": 2, "NПП": "1", "ШифрПроекта": "А"},
            {"ИдСтроки": "Итог"}, {"ИдСтроки": None}]
    assert sl.vor_rows_from_strings(rows) == [{"Наименование": "Монтаж", "Ед": "шт.", "Кол": 2, "Номер": "1", "Шифр": "А"}]


def test_real_sds_svor_vs_vor_book():
    svor_dir = ROOT / "РД" / "ЕСТ-ПМ-80825-Р-2-СДС" / "ИЗМ1 - согласован"
    docs = list(svor_dir.rglob("*СВОР*.docx")) if svor_dir.exists() else []
    book = next((ROOT / "data" / "_pq_work" / "sds_new" / "books").glob("ВОР_*.xlsx"), None) \
        if (ROOT / "data" / "_pq_work" / "sds_new" / "books").exists() else None
    if not (docs and book):
        pytest.skip("нет СВОР СДС или книги ВОР")
    from core.svor import read_svor
    r = sl.link(read_svor(str(docs[0])), sl.read_vor_book(str(book)))
    matched = [x for x in r if x["Статус"] == "совпало"]
    only = [x for x in r if x["Статус"] in ("только в СВОР", "только в ВОР")]
    assert len(matched) >= 100 and len(only) <= 16
