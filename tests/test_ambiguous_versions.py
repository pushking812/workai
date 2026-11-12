from core.query_builder import find_ambiguous_versions


def _row(file_id, code, rev, date, name):
    return {"file_id": file_id, "project_doc_code": code, "revision": rev,
            "revision_date": date, "filename": name}


def test_same_version_in_two_files_is_reported():
    rows = [_row(1, "A-1", 1, "2025-08-15", "a.docx"), _row(2, "A-1", 1, "2025-08-15", "b.docx"),
            _row(2, "A-1", 1, "2025-08-15", "b.docx")]
    result = find_ambiguous_versions(rows)
    assert len(result) == 1
    assert {f["id"] for f in result[0]["files"]} == {1, 2}


def test_different_revision_or_date_is_not_ambiguous():
    rows = [_row(1, "A-1", 1, "2025-08-15", "a.docx"), _row(2, "A-1", 2, "2025-08-15", "b.docx"),
            _row(3, "A-1", 1, "2025-09-01", "c.docx")]
    assert find_ambiguous_versions(rows) == []


def test_several_tables_of_one_file_are_not_ambiguous():
    rows = [_row(1, "A-1", 1, "2025-08-15", "a.docx"), _row(1, "A-1", 1, "2025-08-15", "a.docx")]
    assert find_ambiguous_versions(rows) == []
