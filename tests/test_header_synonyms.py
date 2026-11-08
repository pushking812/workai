"""Справочник синонимов заголовков (Этап 2, коммит 2)."""

from __future__ import annotations

from core import database as db


def _connect(tmp_path):
    return db.init_db(str(tmp_path / "t.db"))


def test_seed_runs_on_init_and_is_idempotent(tmp_path):
    con = _connect(tmp_path)
    count = con.execute("SELECT COUNT(*) FROM header_synonyms").fetchone()[0]
    assert count > 0
    assert db.seed_dictionary(con) == 0
    assert con.execute("SELECT COUNT(*) FROM header_synonyms").fetchone()[0] == count


def test_keys_are_casefolded_normalized(tmp_path):
    con = _connect(tmp_path)
    keys = {r[0] for r in con.execute("SELECT synonym_normalized FROM header_synonyms")}
    assert "едизм" in keys
    assert "nпп" in keys
    assert all(k == k.casefold() and " " not in k for k in keys)


def test_lookup_by_raw_or_normalized(tmp_path):
    con = _connect(tmp_path)
    assert db.get_canonical_for_synonym(con, "Ед. изм.") == "ЕдИзм"
    assert db.get_canonical_for_synonym(con, "ЕдИзм") == "ЕдИзм"
    assert db.get_canonical_for_synonym(con, "№ п/п") == "NПП"
    assert db.get_canonical_for_synonym(con, "№п/п") == "NПП"
    assert db.get_canonical_for_synonym(con, "Количество") == "КолВо"
    assert db.get_canonical_for_synonym(con, "Вид работ") == "НаименованиеРабот"
    assert db.get_canonical_for_synonym(con, "Ссылка на чертежи, спецификации") == "СсылкаНаЧерСпе"
    assert db.get_canonical_for_synonym(con, "Что-то странное") is None
    assert db.get_canonical_for_synonym(con, "") is None


def test_add_synonym_manual_not_overwritten_by_seed(tmp_path):
    con = _connect(tmp_path)
    assert db.add_synonym(con, "Марка", "Марка кабеля", 0.9) is True
    assert db.add_synonym(con, "Другое", "Марка кабеля") is False
    assert db.get_canonical_for_synonym(con, "марка кабеля") == "Марка"
    db.seed_dictionary(con)
    assert db.get_canonical_for_synonym(con, "марка кабеля") == "Марка"


def test_seed_synonyms_do_not_collide():
    seen: dict[str, str] = {}
    for canonical, synonyms in db.SEED_SYNONYMS.items():
        for synonym in (canonical, *synonyms):
            key = db.synonym_key(synonym)
            assert seen.setdefault(key, canonical) == canonical, (key, canonical)
