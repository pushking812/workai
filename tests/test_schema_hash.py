from core import database
from core.transformer.schema_analyzer import analyze_and_save_schema, generate_schema_hash


def test_hash_same_for_spelling_variants():
    assert generate_schema_hash(["№ п/п", "Ед. изм."]) == generate_schema_hash(["№п/п", "ед изм"])


def test_hash_differs_for_other_columns_and_order():
    base = generate_schema_hash(["№ п/п", "Количество"])
    assert base != generate_schema_hash(["№ п/п", "Объем"])
    assert base != generate_schema_hash(["Количество", "№ п/п"])


def test_hash_is_md5_hex():
    value = generate_schema_hash(["A"])
    assert len(value) == 32 and int(value, 16) >= 0


def test_analyze_saves_schema_and_links_files(tmp_path):
    connection = database.init_db(str(tmp_path / "t.db"))
    try:
        file_id = database.add_file(connection, "h1", str(tmp_path / "a.docx"), "a.docx")
        first = analyze_and_save_schema(connection, ["№ п/п", "Ед. изм."], "h1")
        second = analyze_and_save_schema(connection, ["№п/п", "Ед изм"], "h1")
        assert first == second
        schema = database.get_schema(connection, first)
        assert schema["raw_headers"] == ["№ п/п", "Ед. изм."]
        assert schema["normalized_headers"] == ["NПП", "ЕдИзм"]
        assert database.get_file_by_id(connection, file_id)["schema_hash"] == first
        assert analyze_and_save_schema(connection, [], "h1") is None
    finally:
        connection.close()
