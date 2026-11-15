from pathlib import Path

import pytest

from core import cable_link as cl

ROOT = Path(__file__).resolve().parent.parent


def test_normalize_section_variants():
    assert cl.normalize_section("4х2х0,52") == "4x2x0.52"   # кириллическая х
    assert cl.normalize_section("4 × 2 × 0.52") == "4x2x0.52"
    assert cl.normalize_section("2*1,5") == "2x1.5"
    assert cl.normalize_section("нет сечения") == ""


def test_normalize_mark_lookalikes_and_composite():
    assert cl.normalize_mark("КВПЭфнг(А)-HF-5e 4x2x0,52") == cl.normalize_mark("КВПЭфнг(A)-HF-5E")
    # составная ячейка: берётся первая марка
    assert cl.normalize_mark("ПуГВнг(А)-LS цвет красный, ПуГВнг(А)-LS цвет синий") == cl.normalize_mark("ПуГВнг(А)-LS")


def test_mark_words_drop_category_word():
    assert "5e" in cl.mark_words("F/UTP Cat. 5e LSZH")
    assert "5e" in cl.mark_words("Витая пара F/UTP кат.5E 4х2х0,52 solid LSZH")
    assert "cat" not in cl.mark_words("F/UTP Cat. 5e LSZH")


def test_so_meters_units():
    assert cl.so_meters("м", "45") == 45
    assert cl.so_meters("км.", "1,5") == 1500
    assert cl.so_meters("шт.", "5") is None


def test_exact_key_sums_both_sides():
    kzh = [{"Марка": "ТППнг(А)-HF", "Сечение": "20х2х0,64", "Длина": "50"},
           {"Марка": "ТППнг(А)-HF", "Сечение": "20x2x0,64", "Длина": "55"}]
    so = [{"Наименование": "Кабель телефонный", "Тип": "ТППнг(А)-HF 20х2х0,64", "Ед": "м", "Кол": "105"}]
    r = cl.link(kzh, so)
    assert len(r) == 1 and r[0]["Статус"] == "совпало" and r[0]["Режим"] == "ключ"


def test_words_mode_finds_single_candidate():
    kzh = [{"Марка": "F/UTP Cat. 5e LSZH", "Сечение": "4x2x0,52", "Длина": "1979"}]
    so = [{"Наименование": "Витая пара F/UTP кат.5E 4х2х0,52 solid LSZH нг(А)-HF", "Тип": "LC1-C5E04-327-T-P-R",
           "Ед": "м", "Кол": "1979"}]
    r = cl.link(kzh, so)
    assert [x["Статус"] for x in r] == ["совпало"] and r[0]["Режим"] == "слова"


def test_words_mode_ambiguous_is_not_linked():
    kzh = [{"Марка": "UTP 5e", "Сечение": "4x2x0,52", "Длина": "10"}]
    so = [{"Наименование": "Кабель UTP 5e", "Тип": "A 4х2х0,52", "Ед": "м", "Кол": "10"},
          {"Наименование": "Кабель UTP 5e", "Тип": "B 4х2х0,52", "Ед": "м", "Кол": "10"}]
    st = sorted(x["Статус"] for x in cl.link(kzh, so))
    assert st == ["только в КЖ", "только в СО", "только в СО"]


def test_difference_and_tolerance():
    so = [{"Наименование": "Кабель", "Тип": "К 2х1", "Ед": "м", "Кол": "100"}]
    near = cl.link([{"Марка": "К", "Сечение": "2х1", "Длина": "100,4"}], so)
    far = cl.link([{"Марка": "К", "Сечение": "2х1", "Длина": "110"}], so)
    assert near[0]["Статус"] == "совпало"
    assert far[0]["Статус"] == "КЖ больше" and far[0]["Разница"] == 10


def test_so_units_not_length_are_ignored_and_km_converted():
    so = [{"Наименование": "Кабель", "Тип": "К 2х1", "Ед": "км", "Кол": "0,1"},
          {"Наименование": "Патч-корд", "Тип": "PC 2х1", "Ед": "шт.", "Кол": "3"}]
    r = cl.link([{"Марка": "К", "Сечение": "2х1", "Длина": "100"}], so)
    assert len(r) == 1 and r[0]["Статус"] == "совпало"


def test_non_cable_meters_are_not_reported_as_only_in_so():
    so = [{"Наименование": "Труба стальная", "Тип": "ГОСТ 3262 50x50", "Ед": "м", "Кол": "9"}]
    assert cl.link([], so) == []


def test_cable_channel_is_not_cable():
    so = [{"Наименование": "Кабель-канал", "Тип": "25x20x2000", "Ед": "м", "Кол": "5"}]
    assert cl.link([], so) == []


def test_other_mark_same_section_and_volume_is_flagged():
    kzh = [{"Марка": "КСБнг(А)-FRHF", "Сечение": "4х2х0,5", "Длина": "70"}]
    so = [{"Наименование": "Кабель", "Тип": "КПСнг(А)-FRHF 4х2х0,5", "Ед": "м", "Кол": "70"}]
    r = cl.link(kzh, so)
    assert len(r) == 1 and r[0]["Статус"] == "марка отличается" and r[0]["Режим"] == "сечение+объём"


def test_other_mark_with_different_volume_is_not_paired():
    kzh = [{"Марка": "КСБнг", "Сечение": "4х2х0,5", "Длина": "70"}]
    so = [{"Наименование": "Кабель", "Тип": "КПСнг 4х2х0,5", "Ед": "м", "Кол": "10"}]
    assert sorted(x["Статус"] for x in cl.link(kzh, so)) == ["только в КЖ", "только в СО"]


def test_header_column_choice_skips_pipe_columns():
    from core.cable_docs import _col
    h = ["ПроходЧерез|Трубу|ДлинаМ", "КабельПровод|ПоПроекту|ДлинаМ", "Проложен|ДлинаМ"]
    assert _col(h, "ДлинаМ") == 1
    assert _col(["ПроходЧерез|Трубу|ДлинаМ", "Проложен|ДлинаМ"], "ДлинаМ") is None


def test_so_rows_from_strings_filters_like_pq_query():
    from core.cable_docs import so_rows_from_strings
    rows = [{"ИдСтроки": "1", "NПП": "5", "НаименованиеИТехХар": "Кабель", "ТипМаркаОбозначение": "К 2х1",
             "ЕдИзм": "м", "КолВо": 3, "ШифрПроекта": "А"},
            {"ИдСтроки": None, "NПП": "6"}, {"ИдСтроки": "2", "NПП": " "}]
    assert so_rows_from_strings(rows) == [{"Наименование": "Кабель", "Тип": "К 2х1", "Ед": "м", "Кол": 3, "Шифр": "А"}]


def test_link_by_project_does_not_mix_codes():
    kzh = [{"Марка": "К", "Сечение": "2х1", "Длина": "10", "Шифр": "А"},
           {"Марка": "К", "Сечение": "2х1", "Длина": "99", "Шифр": "Б"}]
    so = [{"Наименование": "Кабель", "Тип": "К 2х1", "Ед": "м", "Кол": "10", "Шифр": "А"}]
    r = {x["Шифр"]: x["Статус"] for x in cl.link_by_project(kzh, so)}
    assert r == {"А": "совпало", "Б": "только в КЖ"}


def test_project_code_strips_doc_type():
    from core.cable_docs import project_code
    assert project_code("ЕСТ-ПМ-80825-Р-2-СДС.КЖ") == "ЕСТ-ПМ-80825-Р-2-СДС"
    assert project_code("") == ""


def test_real_sds_kzh_vs_so_book_through_project_code():
    from core.cable_docs import read_kzh, read_so_book
    kzh = _find("45. КЖ - 2 этап - СДС.docx")
    book = next((ROOT / "data" / "_pq_work" / "sds_new" / "books").glob("СО_*.xlsx"), None)
    if not (kzh and book):
        pytest.skip("нет КЖ СДС или книги СО")
    r = cl.link_by_project(read_kzh(str(kzh)), read_so_book(str(book)))
    ok = [x for x in r if x["Статус"] == "совпало"]
    assert len(ok) >= 6 and all(x["Шифр"] == "ЕСТ-ПМ-80825-Р-2-СДС" for x in ok)


def _find(pattern):
    hits = list((ROOT / "data" / "converted").glob(pattern))
    return hits[0] if hits else None


def test_real_sds_kzh_vs_so():
    kzh, so = _find("45. КЖ - 2 этап - СДС.docx"), _find("47. СО - 2 этап - СДС изм1.docx")
    if not (kzh and so):
        pytest.skip("нет конвертированных КЖ/СО СДС")
    from core.cable_docs import read_kzh, read_so
    r = cl.link(read_kzh(str(kzh)), read_so(str(so)))
    ok = {x["МаркаКЖ"] + "|" + x["Сечение"]: x for x in r if x["Статус"] == "совпало"}
    assert len(ok) >= 6
    assert ok["F/UTP Cat. 5e LSZH|4x2x0.52"]["Режим"] == "слова"
    assert ok["ТЗПпБПнг(А)-HF|52x4x0.9"]["КЖ_м"] == 1800

