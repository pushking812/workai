"""Сопоставление «только в ВОР» и «только в СО» по наименованию: правило (scripts/check_name_match.py) и запрос Ошибки."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import check_name_match as c  # noqa: E402


def _v(npp, name, cipher="Ш", izm=1):
    return {"ШифрПроекта": cipher, "НомИзмПроекта": izm, "NПП": npp, "НаименованиеРабот": name}


def _s(npp, name, note="", cipher="Ш", izm=1):
    return {"ШифрПроекта": cipher, "НомИзмПроекта": izm, "NПП": npp, "НаименованиеИТехХар": name, "Примечание": note}


def test_words_stems_and_numbers():
    assert "кабел" in c.words("Хомуты кабельные 2,5х200 мм") and "5х200" in c.words("2,5х200")
    assert "мм" not in c.words("20 мм")
    assert "хомут" in c.words("Хомуты") and "хомут" in c.words("Хомут короба")
    assert "30" in c.words("30/100/120В") and "120в" in c.words("30/100/120В")


def test_pair_1_8_and_1_11():
    vor = [_v("1.8", "Монтаж и подключение. Речевой автоинформатор, РИ-7, Подземная часть"),
           _v("1.9", "Подключение. Шкаф коммутации сигнальных цепей, ШК-15")]
    so = [_s("1.11", "Речевой автоинформатор", "подземная часть")]
    assert c.match(vor, so) == [(0, 0, "по наименованию")]


def test_no_false_pair_when_words_missing_or_numbers_differ():
    vor = [_v("7.1", "Врезка установочной коробки громкоговорителя в балюстраду")]
    so = [_s("31", "Громкоговоритель для наклонного хода на балюстраде эскалатора"),
          _s("29", "Громкоговоритель настенный, 30/100/120В")]
    assert c.match(vor, so) == []


def test_other_document_is_not_matched():
    vor = [_v("1.8", "Речевой автоинформатор", cipher="А")]
    so = [_s("1.11", "Речевой автоинформатор", cipher="Б")]
    assert c.match(vor, so) == []


def test_ambiguous_when_two_equal_so_rows():
    vor = [_v("5", "Монтаж хомута короба")]
    so = [_s("20.1", "Хомут короба"), _s("20.2", "Хомут короба")]
    res = c.match(vor, so)
    assert res and all(st == "неоднозначно" for _, _, st in res)


def test_longer_name_wins():
    vor = [_v("5", "Монтаж: Громкоговоритель настенный")]
    so = [_s("1", "Громкоговоритель"), _s("2", "Громкоговоритель настенный")]
    res = c.match(vor, so)
    assert (0, 1, "по наименованию") in res


def test_one_word_so_name_is_not_matched():
    # ЭС2: СО «Заземлено» (табличка) совпало по основе с «заземлителями» из ВОР
    vor = [_v("38", "Проверка наличия цепи между заземлителями и заземленными элементами")]
    so = [_s("44", "«Заземлено»")]
    assert c.match(vor, so) == []


def test_query_requires_two_words():
    text = open(os.path.join(ROOT, "PQ", "ВОР+СО", "запросы", "СвязьПоИмени.pq"), encoding="utf-8").read()
    assert "List.Count(СоИмя{j}) >= 2" in text


def test_query_has_block_for_name_match():
    text = open(os.path.join(ROOT, "PQ", "ВОР+СО", "запросы", "Ошибки.pq"), encoding="utf-8").read()
    assert "связь по наименованию" in text
    assert "СвязьПоИмени" in text


def test_name_pairs_enter_the_final_link_and_intersection():
    # однозначные пары по наименованию - в связи (Пересечение, Связь_ВОР_СО), не в Только_в_*; в Пересечении виден способ связи
    d = os.path.join(ROOT, "PQ", "ВОР+СО", "запросы")
    rd = lambda n: open(os.path.join(d, n), encoding="utf-8").read()
    assert "СвязьПоИмени" in rd("ВОР_СвязьИтог.pq") and '"по наименованию"' in rd("ВОР_СвязьИтог.pq")
    for n in ("Пересечение.pq", "Связь_ВОР_СО.pq", "Только_в_СО.pq", "Только_в_ВОР.pq"):
        assert "ВОР_СвязьИтог" in rd(n), n
    assert "СвязьПоИмени" in rd("Только_в_ВОР.pq")
    assert '"Связь"' in rd("Пересечение.pq") and "по наименованию" in rd("Пересечение.pq")
    # источник остатков не должен зависеть от Только_в_* (иначе цикл запросов)
    assert "Только_в_" not in rd("СвязьПоИмени.pq").replace("Только_в_*", "")


def test_name_query_buffers_lists_and_groups_ambiguous():
    # без List.Buffer Excel падает (ВорЗ{i} заново считает цепочку остатков), неоднозначные сворачиваются в одну запись на строку ВОР
    pq = open(os.path.join(ROOT, 'PQ', 'ВОР+СО', 'запросы', 'СвязьПоИмени.pq'), encoding='utf-8-sig').read()
    assert 'ВорЗ = List.Buffer(' in pq and 'СоЗ = List.Buffer(' in pq
    assert 'НеоднГр = Table.Group(' in pq



def test_no_date_warnings_collapse_over_five_per_date_pair():
    path = os.path.join(ROOT, 'PQ', 'ВОР+СО', 'запросы', 'Ошибки.pq')
    text = open(path, encoding='utf-8-sig').read()
    assert '[Чис] > 5' in text and '[Чис] <= 5' in text
    assert 'БезДатыСвТ' in text and 'БезДатыТ = Table.Combine' in text


def test_section_breaks_tie():
    vor = [_v("5", "Монтаж хомута короба")]
    vor[0]["Раздел"] = "Подземная часть"
    so = [_s("20.1", "Хомут короба"), _s("20.2", "Хомут короба")]
    so[0]["Раздел"] = "Подземная часть"
    so[1]["Раздел"] = "Надземная часть"
    assert (0, 0, "по наименованию") in c.match(vor, so)


def test_section_is_not_a_condition():
    vor = [_v("5", "Монтаж хомута короба")]
    vor[0]["Раздел"] = "Подземная часть"
    so = [_s("20.1", "Хомут короба")]
    so[0]["Раздел"] = "Надземная часть"
    assert c.match(vor, so) == [(0, 0, "по наименованию")]


def test_query_has_section_bonus():
    path = os.path.join(ROOT, 'PQ', 'ВОР+СО', 'запросы', 'СвязьПоИмени.pq')
    text = open(path, encoding='utf-8-sig').read()
    assert 'СоРазд' in text and 'ВорРазд' in text

