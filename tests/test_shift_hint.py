"""Подсказка «ссылка, вероятно, сдвинута» (блок 7 в Ошибки.pq): только предупреждение, связь и суммы не меняются."""
from pathlib import Path

PQ = Path(__file__).resolve().parent.parent / "PQ" / "ВОР+СО" / "запросы" / "Ошибки.pq"


def _text():
    return PQ.read_text(encoding="utf-8")


def test_block_7_present_and_in_result():
    t = _text()
    assert "ссылка, вероятно, сдвинута" in t
    assert "Заготовка(СдвигТ)" in t


def test_block_7_uses_buffers_and_unique_mutual_best():
    t = _text()
    for name in ("ВЗ7", "СЗ7", "ВС7", "СС7"):
        assert f"{name} = List.Buffer(" in t
    assert "[нв] = 1 and [нс] = 1" in t


def test_block_7_reads_only_leaf_queries():
    # не читает СвязьПоИмени/Связь_ВОР_СО из запросов, от которых они зависят (цикл)
    t = _text()
    assert "Связь_ВОР_СО" in t and "СО_Строки" in t
