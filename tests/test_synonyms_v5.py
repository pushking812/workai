"""Справочник КЖ (версия 5): точное сопоставление заголовков кабельного журнала."""

from __future__ import annotations

from core import database as db
from core.transformer.fuzzy_matcher import find_exact_match

MARKA = "КабельПровод|ПоПроекту|Марка"
JILY = "КабельПровод|ПоПроекту|КолЧислоИСечЖил"
DLINA = "КабельПровод|ПоПроекту|ДлинаМ"


def test_kzh_headers_from_parser_match_exactly(tmp_path):
    con = db.init_db(str(tmp_path / "t.db"))
    expected = {
        "ОбозначениеКабеляПро": "ОбозначениеКабеляПро",
        "Трасса|Начало": "Трасса|Начало",
        "Трасса|Конец": "Трасса|Конец",
        MARKA: MARKA,
        JILY: JILY,
        DLINA: DLINA,
        "УчастокТрассыКаб": "УчастокТрассыКаб",
    }
    for header, canonical in expected.items():
        found = find_exact_match(con, header)
        assert found is not None, header
        assert found["suggested_canonical"] == canonical


def test_short_variants_map_to_same_canonical(tmp_path):
    con = db.init_db(str(tmp_path / "t.db"))
    assert db.get_canonical_for_synonym(con, "ПоПроекту|Марка") == MARKA
    assert db.get_canonical_for_synonym(con, "ПоПроекту|КолЧислоИСечЖил") == JILY
    assert db.get_canonical_for_synonym(con, "ПоПроекту|ДлинаМ") == DLINA


def test_xlsx_and_extra_column_names(tmp_path):
    con = db.init_db(str(tmp_path / "t.db"))
    assert db.get_canonical_for_synonym(con, "Участок трассы кабеля") == "УчастокТрассыКаб"
    assert db.get_canonical_for_synonym(con, "Кабель, провод|По проекту|Длина, м") == DLINA
    assert db.get_canonical_for_synonym(con, "Обозначение кабеля, провода") == "ОбозначениеКабеляПро"


def test_migration_v4_to_v5_keeps_user_synonyms(tmp_path):
    path = str(tmp_path / "t.db")
    con = db.init_db(path)
    con.execute("DELETE FROM header_synonyms WHERE canonical_name = 'УчастокТрассыКаб'")
    db.add_synonym(con, "МойСтолбец", "моя колонка")
    con.execute("PRAGMA user_version = 4")
    con.commit()
    con.close()
    con = db.init_db(path)
    assert db.get_canonical_for_synonym(con, "Участок трассы кабеля") == "УчастокТрассыКаб"
    assert db.get_canonical_for_synonym(con, "Моя колонка") == "МойСтолбец"
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
