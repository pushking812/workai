"""Решения по заголовкам без роли и правка справочника заголовков."""

from __future__ import annotations

import os

import pytest

from api.controller import Controller
from core import database, header_dictionary, query_builder

TEMPLATE = query_builder.TEMPLATES["ВОР"]["path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(TEMPLATE), reason="нет шаблона ВОР")


def _file(db, tmp_path, name, header_line):
    connection = database.init_db(db)
    try:
        file_id = database.add_file(
            connection, "h_" + name, str(tmp_path / name), name,
            {"doc_code": "ЕСТ-ПМ-1-СС.ВОР", "project_code": "ЕСТ-ПМ", "section_code": "1-СС",
             "doc_type": "ВОР", "revision": "1", "revision_date": "2026-05-07",
             "sheet": 1, "sheets_total": 1, "stamp_status": "OK"},
        )
        csv = tmp_path / f"h_{name}_table_1.csv"
        csv.write_text(header_line + "\n1;2\n", encoding="utf-8-sig")
        connection.execute("UPDATE files SET csv_path = ? WHERE id = ?", (str(csv), file_id))
        connection.commit()
        return file_id
    finally:
        connection.close()


def _ctl(tmp_path, monkeypatch):
    monkeypatch.setattr(query_builder, "QUERIES_DIR", str(tmp_path / "out"))
    db = str(tmp_path / "t.db")
    return Controller(db), db


def test_check_headers_lists_unknown_with_candidates(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    a = _file(db, tmp_path, "a.docx", "Кол-во;Мой столбец")
    b = _file(db, tmp_path, "b.docx", "Кол-во;Мой столбец")
    result = ctl.check_headers([a, b])
    assert [u["header"] for u in result["unresolved"]] == ["Мой столбец"]
    item = result["unresolved"][0]
    assert item["count"] == 2 and item["files"][0]["column"] == 2 and not item["suspicious"]
    assert "КолВо" in result["roles"] and len(item["candidates"]) <= 3


def test_data_row_header_is_flagged(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _file(db, tmp_path, "a.docx", "18;Гидравлические испытания")
    assert all(u["suspicious"] for u in ctl.check_headers([file_id])["unresolved"])


def test_assign_is_remembered(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _file(db, tmp_path, "a.docx", "Мой столбец")
    out = ctl.apply_header_decisions([{"header": "Мой столбец", "action": "assign", "role": "КолВо"}])
    assert out["status"] == "ok" and out["applied"] == 1
    assert ctl.check_headers([file_id])["unresolved"] == []
    book = ctl.build_queries([file_id], opener=lambda p: None)["books"][0]
    assert book["unresolved_headers"] == []


def test_ignore_is_remembered_and_can_be_returned(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _file(db, tmp_path, "a.docx", "Мой столбец")
    ctl.apply_header_decisions([{"header": "Мой столбец", "action": "ignore"}])
    assert ctl.check_headers([file_id])["unresolved"] == []
    ignored = ctl.get_dictionary()["ignored"]
    assert [i["raw"] for i in ignored] == ["Мой столбец"]
    ctl.edit_dictionary("unignore", {"key": ignored[0]["key"]})
    assert len(ctl.check_headers([file_id])["unresolved"]) == 1


def test_skip_stores_nothing(tmp_path, monkeypatch):
    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _file(db, tmp_path, "a.docx", "Мой столбец")
    ctl.apply_header_decisions([{"header": "Мой столбец", "action": "skip"}])
    assert len(ctl.check_headers([file_id])["unresolved"]) == 1


def test_new_role_becomes_reference_column(tmp_path, monkeypatch):
    import openpyxl

    ctl, db = _ctl(tmp_path, monkeypatch)
    file_id = _file(db, tmp_path, "a.docx", "Кол-во;Масса, кг")
    out = ctl.apply_header_decisions([{"header": "Масса, кг", "action": "new", "role": "Масса"}])
    assert out["status"] == "ok"
    book = ctl.build_queries([file_id], opener=lambda p: None)["books"][0]
    assert book["unresolved_headers"] == []
    ws = openpyxl.load_workbook(book["path"])["Справочники"]
    table = ws.tables["СправочникКолонок"]
    rows = [[c.value for c in r] for r in ws[table.ref]]
    assert rows[0][-1] == "Масса" and "Масса" in [c.name for c in table.tableColumns]
    assert "Масса, кг" in [r[-1] for r in rows[1:]]


def test_dictionary_editing(tmp_path, monkeypatch):
    ctl, _db = _ctl(tmp_path, monkeypatch)
    names = {c["name"] for c in ctl.get_dictionary()["canonical"]}
    assert "КолВо" in names
    assert ctl.edit_dictionary("add_canonical", {"name": "Масса"})["status"] == "ok"
    assert ctl.edit_dictionary("add_canonical", {"name": "Масса"})["status"] == "error"
    ctl.edit_dictionary("add_alias", {"canonical": "Масса", "text": "Вес, кг"})
    current = {c["name"]: c for c in ctl.get_dictionary()["canonical"]}["Масса"]
    assert current["user_created"] and database.synonym_key("Вес, кг") in current["synonyms"]
    # синоним переносится к другому имени
    ctl.edit_dictionary("add_alias", {"canonical": "КолВо", "text": "Вес, кг"})
    after = {c["name"]: c for c in ctl.get_dictionary()["canonical"]}
    assert database.synonym_key("Вес, кг") in after["КолВо"]["synonyms"] and database.synonym_key("Вес, кг") not in after["Масса"]["synonyms"]
    # последний синоним не удаляется, имя удаляется целиком
    assert ctl.edit_dictionary("remove_alias", {"key": "масса"})["status"] == "error"
    assert ctl.edit_dictionary("rename_canonical", {"old": "Масса", "new": "МассаКг"})["status"] == "ok"
    result = ctl.edit_dictionary("delete_canonical", {"name": "МассаКг"})
    assert "МассаКг" not in {c["name"] for c in result["canonical"]}
    assert ctl.edit_dictionary("нет такой", {})["status"] == "error"


def test_user_roles_table_survives_reopen(tmp_path):
    db = str(tmp_path / "t.db")
    connection = database.init_db(db)
    header_dictionary.add_canonical(connection, "Масса")
    connection.close()
    connection = database.init_db(db)
    try:
        assert header_dictionary.user_roles(connection) == ["Масса"]
    finally:
        connection.close()


def test_synonym_labels_keep_case(tmp_path):
    connection = database.init_db(str(tmp_path / 't.db'))
    try:
        header_dictionary.add_canonical(connection, 'Масса')
        header_dictionary.set_alias(connection, 'Масса', 'Вес, кг')
        data = header_dictionary.list_dictionary(connection)
        cur = next(c for c in data['canonical'] if c['name'] == 'Масса')
        assert cur['labels'][database.synonym_key('Вес, кг')] == 'Вес, кг'
        seed = next(c for c in data['canonical'] if c['name'] == 'КабельПровод|ПоПроекту|КолЧислоИСечЖил')
        assert any(v != k for k, v in seed['labels'].items())
        # Каноническое имя не показывается среди своих синонимов.
        for item in data['canonical']:
            assert database.synonym_key(item['name']) not in item['synonyms']
    finally:
        connection.close()


def test_rename_alias_and_ignored(tmp_path):
    connection = database.init_db(str(tmp_path / 'd.db'))
    try:
        name = header_dictionary.add_canonical(connection, 'Роль1')
        header_dictionary.set_alias(connection, name, 'Старый')
        header_dictionary.rename_alias(connection, database.synonym_key('Старый'), name, 'Новый Вар')
        keys = header_dictionary.list_dictionary(connection)['canonical']
        syn = [c for c in keys if c['name'] == name][0]
        assert database.synonym_key('Новый Вар') in syn['synonyms']
        assert database.synonym_key('Старый') not in syn['synonyms']
        header_dictionary.ignore_header(connection, 'Мусор')
        header_dictionary.rename_ignored(connection, database.synonym_key('Мусор'), 'Мусор 2')
        assert [i['raw'] for i in header_dictionary.list_dictionary(connection)['ignored']] == ['Мусор 2']
    finally:
        connection.close()
