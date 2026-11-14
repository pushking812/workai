"""Ключ связи ВОР–СО в книге ВОР+СО: строгий (с датой), затем без даты с предупреждением на листе «Ошибки»."""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import make_vor_so_template as m  # noqa: E402


def _queries(tmp_path):
    old = m.WORK
    m.WORK = str(tmp_path / "q")
    try:
        folder = m.prepare_queries()
        return {n[:-3]: open(os.path.join(folder, n), encoding="utf-8").read() for n in os.listdir(folder) if n.endswith(".pq")}
    finally:
        m.WORK = old


def test_strict_query_is_vor_code_and_resolver_reads_it(tmp_path):
    q = _queries(tmp_path)
    assert "ВОР_Строки" in q["ВОР_СвязьСОСтрогая"] and "ДатаИзм" in q["ВОР_СвязьСОСтрогая"]
    assert "ВОР_СвязьСОСтрогая" in q["ВОР_СвязьСО"]
    assert "СвязьБезДаты" in q["ВОР_СвязьСО"] and "ДатаСО" in q["ВОР_СвязьСО"]
    assert "ВОР_СвязьСОСтрогая" in m.CONNECTION_ONLY and "ВОР_СвязьСО" in m.CONNECTION_ONLY


def test_errors_sheet_lists_dateless_links(tmp_path):
    q = _queries(tmp_path)
    assert "связь без даты" in q["Ошибки"]
    assert "СвязьБезДаты" in q["Ошибки"]
    shutil.rmtree(tmp_path / "q", ignore_errors=True)
