from core import database
from core.transformer.fuzzy_matcher import find_exact_match


def _db(tmp_path):
    return database.init_db(str(tmp_path / "t.db"))


def test_exact_match_by_synonym(tmp_path):
    connection = _db(tmp_path)
    result = find_exact_match(connection, "Ед. изм.")
    assert result["suggested_canonical"] == "ЕдИзм"
    assert result["score"] == 100.0
    assert result["is_exact_match"] is True
    assert result["requires_manual_review"] is False
    assert result["source_header"] == "Ед. изм."


def test_exact_match_accepts_normalized_and_spelling_variants(tmp_path):
    connection = _db(tmp_path)
    assert find_exact_match(connection, "ЕдИзм")["suggested_canonical"] == "ЕдИзм"
    assert find_exact_match(connection, "№п/п")["suggested_canonical"] == "NПП"
    assert find_exact_match(connection, "Количество")["suggested_canonical"] == "КолВо"


def test_exact_match_unknown_or_empty_returns_none(tmp_path):
    connection = _db(tmp_path)
    assert find_exact_match(connection, "Совсем другой заголовок") is None
    assert find_exact_match(connection, "") is None


def test_exact_match_sees_manual_synonym(tmp_path):
    connection = _db(tmp_path)
    database.add_synonym(connection, "КолВо", "Кол-во по проекту")
    assert find_exact_match(connection, "Кол-во по проекту")["suggested_canonical"] == "КолВо"
