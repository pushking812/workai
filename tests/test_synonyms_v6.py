"""Справочник КЖ (версия 6): блок «Проход через»."""

from __future__ import annotations

from core import database as db
from core.transformer.fuzzy_matcher import find_exact_match

NAMES = (
    "ПроходЧерез|Трубу|Обозначение",
    "ПроходЧерез|Трубу|ДиамПоСтаМм",
    "ПроходЧерез|Трубу|ДлинаМ",
    "ПроходЧерез|ПротяжЯщикN",
)


def test_pass_through_headers_match_exactly(tmp_path):
    con = db.init_db(str(tmp_path / "t.db"))
    for name in NAMES:
        found = find_exact_match(con, name)
        assert found is not None, name
        assert found["suggested_canonical"] == name


def test_migration_v5_to_v6(tmp_path):
    path = str(tmp_path / "t.db")
    con = db.init_db(path)
    con.execute("DELETE FROM header_synonyms WHERE canonical_name LIKE 'ПроходЧерез%'")
    db.add_synonym(con, "МойСтолбец", "моя колонка")
    con.execute("PRAGMA user_version = 5")
    con.commit()
    con.close()
    con = db.init_db(path)
    for name in NAMES:
        assert db.get_canonical_for_synonym(con, name) == name
    assert db.get_canonical_for_synonym(con, "Моя колонка") == "МойСтолбец"
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
