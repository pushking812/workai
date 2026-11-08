from core import database
from core.transformer.fuzzy_matcher import find_best_match


def _db(tmp_path):
    return database.init_db(str(tmp_path / "t.db"))


def test_best_match_prefers_exact(tmp_path):
    connection = _db(tmp_path)
    result = find_best_match(connection, "Ед. изм.")
    assert result["suggested_canonical"] == "ЕдИзм"
    assert result["score"] == 100.0
    assert result["is_exact_match"] is True
    assert result["requires_manual_review"] is False


def test_fuzzy_finds_work_name_from_tz(tmp_path):
    connection = _db(tmp_path)
    for header in ("Наименование работы", "Наименование работ"):
        result = find_best_match(connection, header)
        assert result["suggested_canonical"] == "НаименованиеРабот"
        assert result["score"] >= 85
        assert result["requires_manual_review"] is False
    assert find_best_match(connection, "Наименование работы")["is_exact_match"] is False


def test_low_score_requires_manual_review(tmp_path):
    connection = _db(tmp_path)
    result = find_best_match(connection, "Совсем другой заголовок")
    assert result["is_exact_match"] is False
    assert result["score"] < 85
    assert result["requires_manual_review"] is True


def test_threshold_is_configurable(tmp_path):
    connection = _db(tmp_path)
    strict = find_best_match(connection, "Наименование работы", threshold=99)
    assert strict["suggested_canonical"] == "НаименованиеРабот"
    assert strict["requires_manual_review"] is True


def test_empty_header_and_empty_dictionary(tmp_path):
    connection = _db(tmp_path)
    empty = find_best_match(connection, "")
    assert empty["suggested_canonical"] is None
    assert empty["requires_manual_review"] is True
    connection.execute("DELETE FROM header_synonyms")
    connection.commit()
    none = find_best_match(connection, "Количество")
    assert none["suggested_canonical"] is None
    assert none["requires_manual_review"] is True


def test_hyphen_abbreviation_matches_full_word(tmp_path):
    connection = _db(tmp_path)
    connection.execute("DELETE FROM header_synonyms WHERE synonym_normalized = 'колво'")
    connection.commit()
    for header in ("Кол-во", "кол.-во", "Колич-во"):
        result = find_best_match(connection, header)
        assert result["suggested_canonical"] == "КолВо", header
        assert result["score"] == 90.0
        assert result["requires_manual_review"] is False
        assert result["method"] == "abbreviation"


def test_hyphen_abbreviation_for_non_seed_word(tmp_path):
    connection = _db(tmp_path)
    result = find_best_match(connection, "Наим-ние")
    assert result["suggested_canonical"] == "НаименованиеРабот"
    assert result["requires_manual_review"] is False


def test_hyphen_abbreviation_ignores_short_or_foreign(tmp_path):
    connection = _db(tmp_path)
    for header in ("р-н", "в-во", "Кол-вы", "Ж-д путь"):
        result = find_best_match(connection, header)
        assert result.get("method") != "abbreviation", header
        assert result["requires_manual_review"] is True, header


def test_kol_vo_is_exact_synonym(tmp_path):
    connection = _db(tmp_path)
    for header in ("Кол-во", "Количество"):
        result = find_best_match(connection, header)
        assert result["suggested_canonical"] == "КолВо"
        assert result["is_exact_match"] is True
