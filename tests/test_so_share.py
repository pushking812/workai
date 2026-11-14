"""Связь_ВОР_СО: единый алгоритм распределения (долю СО и ВОР_УчтеноОдинРаз считает запрос)."""
from pathlib import Path

PQ = Path(__file__).resolve().parent.parent / "PQ" / "ВОР+СО" / "запросы" / "Связь_ВОР_СО.pq"


def _text():
    return PQ.read_text(encoding="utf-8-sig")


def test_share_column_is_number_and_vor_flag_is_int():
    t = _text()
    assert '{"СО_УчтеноОдинРаз", type number}' in t
    assert '{"ВОР_УчтеноОдинРаз", Int64.Type}' in t


def test_share_is_proportional_to_kolvo_with_same_unit():
    t = _text()
    assert "кол{k} / List.Sum(ко)" in t
    # деление только при одном разделе и сумме КолВо = СО (допуск Равно), в единице СО
    assert "Равно(List.Sum(ко), ско)" in t and "одинРаздел" in t
    assert "ед{_} = Ед(сЗап{j}[СО_ЕдИзм])" in t


def test_vor_counted_once_flag():
    t = _text()
    assert "each if [_н] = [_мин] then 1 else 0, Int64.Type" in t


def test_all_statuses_known_to_errors_query():
    errors = (PQ.parent / "Ошибки.pq").read_text(encoding="utf-8-sig")
    for status in ("ВОР без доли", "доля по КолВо", "проверить вручную", "единицы разные",
                   "нет аналога (другая единица)", "числа не совпали"):
        assert f'"{status}"' in _text()
        assert f'"{status}"' in errors
    # операция и «по объёму» - штатные режимы, в Ошибки не попадают
    assert '"операция над тем же материалом"' in _text()


def test_comparable_flag_and_reference_volume():
    t = _text()
    assert "Сравнимо = if р[вид] = \"без\" then 0 else 1" in t
    assert '{"СО_Справочно", type number}, {"Сравнимо", Int64.Type}' in t
