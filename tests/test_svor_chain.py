from core.svor_chain import check_chain


def row(name, p, r, section="Раздел", cd=None, color="", unit="м"):
    return {"Раздел": section, "Номер": "", "Наименование": name, "Ед": unit, "П": p, "Р": r,
            "Откл": r - p if cd is None else cd, "Примечание": "", "Цвет": color}


def codes(errs):
    return sorted(e["Код"] for e in errs)


def test_clean_chain_has_no_errors():
    a = [row("Кабель А", 10, 20), row("Кабель Б", 5, 0)]
    b = [row("Кабель А", 20, 25), row("Кабель Б", 0, 0), row("Новый", 0, 3)]
    chain, errs = check_chain({1: a, 2: b})
    assert errs == []
    rec = [c for c in chain if c["Наименование"] == "Кабель А"][0]
    assert rec["Изм 1 Р"] == 20 and rec["Изм 2 П"] == 20


def test_p_not_equal_previous_r():
    chain, errs = check_chain({1: [row("Кабель А", 10, 20)], 2: [row("Кабель А", 10, 25)]})
    assert codes(errs) == ["цепочка"]


def test_row_vanished_and_new_with_p():
    a = [row("Кабель А", 10, 20)]
    b = [row("Другой", 4, 6)]
    _, errs = check_chain({1: a, 2: b})
    assert codes(errs) == ["нет_предшественника", "пропала"]


def test_vanished_with_zero_r_is_fine():
    _, errs = check_chain({1: [row("Кабель А", 10, 0)], 2: []})
    assert errs == []


def test_missing_intermediate():
    _, errs = check_chain({1: [row("А", 1, 1)], 3: [row("А", 1, 1)]})
    assert codes(errs) == ["нет_изменения"]


def test_deviation_not_r_minus_p_and_green():
    _, errs = check_chain({1: [row("А", 2, 5, cd=1, color="зелёный")]})
    assert codes(errs) == ["откл_не_равно_Р-П", "цвет"]


def test_tail_name_pairs_by_head():
    a = [row("Монтаж труб Наземная часть здания 1", 4, 6)]
    b = [row("Монтаж труб Подземная часть здания 2", 6, 7)]
    _, errs = check_chain({1: a, 2: b})
    assert codes(errs) == ["имя_изменилось"]


def test_duplicate_name_is_paired_by_order_without_error():
    a = [row("Грунт ручным способом", 1, 1), row("Грунт ручным способом", 2, 3)]
    b = [row("Грунт ручным способом", 1, 1), row("Грунт ручным способом", 3, 4)]
    _, errs = check_chain({1: a, 2: b})
    assert errs == []


def test_renamed_row_paired_by_words_and_number():
    a = [row("Укладка труб Электропайп d=160 с учётом запаса", 180, 220)]
    b = [row("Укладка труб Электропайп d=160 с учётом запаса и рядов", 220, 230)]
    _, errs = check_chain({1: a, 2: b})
    assert codes(errs) == ["имя_изменилось"]
