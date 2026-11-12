"""Миграция справочника на версию 4 (ФормулаРасчета, NЛСР, без «примечание»)."""

from __future__ import annotations

from core import database as db


def test_v4_seed_has_new_names_and_no_primechanie(tmp_path):
    con = db.init_db(str(tmp_path / "t.db"))
    full = "Формула расчета, расчет объемов работ и расхода материалов"
    assert db.get_canonical_for_synonym(con, full) == "ФормулаРасчета"
    assert db.get_canonical_for_synonym(con, "№ в ЛСР") == "NЛСР"
    assert db.get_canonical_for_synonym(con, "Примечания") is None


def test_migration_v3_to_v4(tmp_path):
    path = str(tmp_path / "t.db")
    con = db.init_db(path)
    con.execute(
        "DELETE FROM header_synonyms WHERE canonical_name IN ('ФормулаРасчета', 'NЛСР')"
    )
    db.add_synonym(con, "СсылкаНаЧерСпе", "примечание")
    db.add_synonym(con, "МойСтолбец", "моя колонка")
    con.execute("PRAGMA user_version = 3")
    con.commit()
    con.close()
    con = db.init_db(path)
    assert db.get_canonical_for_synonym(con, "№ в ЛСР") == "NЛСР"
    # из ссылки на чертежи «примечание» убрано; с версии 8 это роль СО «Примечание»
    assert db.get_canonical_for_synonym(con, "Примечание") == "Примечание"
    assert db.get_canonical_for_synonym(con, "Моя колонка") == "МойСтолбец"
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_migration_keeps_synonym_moved_by_user(tmp_path):
    path = str(tmp_path / "t.db")
    con = db.init_db(path)
    con.execute(
        "UPDATE header_synonyms SET canonical_name = 'Примечание' "
        "WHERE synonym_normalized = ?",
        (db.synonym_key("примечание"),),
    )
    db.add_synonym(con, "Примечание", "примечание")
    con.execute("PRAGMA user_version = 3")
    con.commit()
    con.close()
    con = db.init_db(path)
    assert db.get_canonical_for_synonym(con, "Примечание") == "Примечание"
