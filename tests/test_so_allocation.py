"""Единое правило распределения объёма СО по строкам ВОР (core/so_allocation.py), случаи из СОУЭ 1 и 2 этап."""
from core.so_allocation import allocate


def V(name, ed, kol):
    return {"name": name, "ed": ed, "kol": kol}


def S(name, ed, kol, note=""):
    return {"name": name, "ed": ed, "kol": kol, "note": note}


def pairs(res):
    return {(i, j): round(s, 4) for i, j, s in res[0]}


def test_parallel_split_by_zone_and_part():
    vor = [V("Прокладка. Кабель огнестойкий 1x2x1,5, КПСнг(А)-FRHF Зона 1.03 Подземная часть", "м", 114),
           V("Прокладка. Кабель огнестойкий 1x2x1,5, КПСнг(А)-FRHF Зона 1.05 Наземная часть.", "м", 64),
           V("Прокладка. Кабель огнестойкий 1x2x1,5, КПСнг(А)-FRHF Зона 2.01 Наземная часть", "м", 158)]
    so = [S("Кабель огнестойкий 1x2x1,5", "м", 114, "Зона 1.03 подземная часть"),
          S("Кабель огнестойкий 1x2x1,5", "м", 64, "Зона 1.05 наземная часть"),
          S("Кабель огнестойкий 1x2x1,5", "м", 158, "Зона 2.01 наземная часть")]
    assert pairs(allocate(vor, so)) == {(0, 0): 1.0, (1, 1): 1.0, (2, 2): 1.0}


def test_part_only_split_14_3():
    vor = [V("Монтаж. Кабель-каналы ККМО 25х20х2000 Наземная часть", "м", 1000),
           V("Монтаж. Кабель-каналы ККМО 25х20х2000 Подземная часть", "м", 114)]
    so = [S("Кабель-каналы ККМО 25х20х2000", "м", 1000, "наземная часть"),
          S("Кабель-каналы ККМО 25х20х2000", "м", 114, "подземная часть")]
    assert pairs(allocate(vor, so)) == {(0, 0): 1.0, (1, 1): 1.0}


def test_vor_splits_so_single_proportional_12_13():
    vor = [V("Прокладка. Труба ПВХ D20мм Наземная часть.", "м", 438),
           V("Прокладка. Труба ПВХ D20мм Подземная часть.", "м", 290)]
    so = [S("Труба ПВХ гибкая D20мм", "м", 728)]
    got = pairs(allocate(vor, so))
    assert got == {(0, 0): round(438 / 728, 4), (1, 0): round(290 / 728, 4)}


def test_unit_decides_22():
    vor = [V("Нарезка стальной трубы в размер закладных стальная труба 26х2 в наземной части", "шт", 169),
           V("Монтаж закладных устройств в стенах Стальная труба 26х2", "м", 30)]
    so = [S("Труба стальная 26х2", "м", 30, "наземная часть")]
    res = allocate(vor, so)
    assert pairs(res) == {(1, 0): 1.0, (0, 0): 0.0}
    assert ("нет аналога: другая единица", 0, 0) in res[1]


def test_numbers_exclude_foreign_row_14_11():
    vor = [V("Прокладка. Кабель огнестойкий 1x2x1,78, КСБКнг(А)-FRHF Зона 1.13 Наземная часть", "м", 10),
           V("Прокладка. Кабель огнестойкий 1x2x1,5, КПСнг(А)-FRHF Зона 1.13 Наземная часть", "м", 33)]
    so = [S("Кабель огнестойкий 1x2x1,78", "м", 10, "Зона 1.13 наземная часть")]
    assert pairs(allocate(vor, so)) == {(0, 0): 1.0, (1, 0): 0.0}


def test_busy_row_yields_without_common_words():
    # СОУЭ 2: «наземная часть» и «Зоны 2.01-2.05» в ВОР называются иначе
    vor = [V("Монтаж на поверхности. Кабель ОКЛ", "м", 470),
           V("Демонтаж. Кабель ОКЛ Зоны 2.01-2.05", "м", 65)]
    so = [S("Кабель ОКЛ", "м", 470, "наземная часть"),
          S("Кабель ОКЛ", "м", 65, "Зоны 2.01-2.05")]
    assert pairs(allocate(vor, so)) == {(0, 0): 1.0, (1, 1): 1.0}


def test_so_split_vor_single_each_so_row_counted_once():
    vor = [V("Установка. Коробка КМО", "шт", 10)]
    so = [S("Коробка КМО", "шт", 4, "Зона 1"), S("Коробка КМО", "шт", 6, "Зона 2")]
    assert pairs(allocate(vor, so)) == {(0, 0): 1.0, (0, 1): 1.0}


def test_shares_of_each_so_row_sum_to_one():
    vor = [V("Прокладка Труба Наземная", "м", 3), V("Прокладка Труба Подземная", "м", 5),
           V("Прокладка Труба Прочее", "м", 2)]
    so = [S("Труба", "м", 10)]
    res, _ = allocate(vor, so)
    assert abs(sum(s for _, j, s in res if j == 0) - 1.0) < 1e-9


def Vs(name, ed, kol, section):
    return dict(V(name, ed, kol), section=section)


def test_operations_same_section_each_equals_so():
    vor = [Vs("Прокладка. Труба ПНД D32", "м", 61, "1"), Vs("Гидроиспытания. Труба ПНД D32", "м", 61, "1")]
    so = [S("Труба ПНД D32", "м", 61)]
    res = allocate(vor, so)
    assert pairs(res) == {(0, 0): 1.0, (1, 0): 0.0}
    assert ("операция", 1, 0) in res[1]


def test_different_sections_do_not_split():
    vor = [Vs("Труба D20 А", "м", 3, "1"), Vs("Труба D20 Б", "м", 5, "2")]
    so = [S("Труба D20", "м", 8)]
    res = allocate(vor, so)
    assert pairs(res) == {(0, 0): 1.0, (1, 0): 0.0}
    assert ("проверить вручную", 0, 0) in res[1]


def test_unit_mismatch_gets_no_analog():
    vor = [V("Заделка проходок. Труба D20", "шт", 5), V("Монтаж. Труба D20", "м", 30)]
    so = [S("Труба D20", "м", 30)]
    res = allocate(vor, so)
    assert ("нет аналога: другая единица", 0, 0) in res[1]


def test_only_other_unit_keeps_so_total():
    res = allocate([V("Скоба D20", "м", 10)], [S("Скоба D20", "шт", 1456)])
    assert pairs(res) == {(0, 0): 1.0}


def test_single_row_equal_to_so_wins():
    vor = [Vs("Измерение. Кабель К1", "м", 40, "1"), Vs("Прокладка. Кабель К1", "м", 100, "1"),
           Vs("Маркировка. Кабель К1", "м", 7, "1")]
    res = allocate(vor, [S("Кабель К1", "м", 100)])
    assert pairs(res)[(1, 0)] == 1.0 and ("по объёму", 1, 0) in res[1]
