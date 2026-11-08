"""Хэш файла и определение версии (Этап 1, пп. 3 и 6)."""

from __future__ import annotations

import pytest

from core import database
from core.hasher import (
    RESULT_ALREADY_EXISTS,
    RESULT_NEW,
    RESULT_NEW_VARIANT,
    RESULT_NEW_VERSION,
    calculate_sha256,
    compute_variant_group,
    process_file_entry,
)

CODE = "ЕСТ-ПМ-80825-Р-1-ИСВН.ВОР"


def make_file(folder, name: str, content: bytes):
    path = folder / name
    path.write_bytes(content)
    return str(path)


def stamp(revision: str = "0", date: str | None = "2025-08-01", code: str = CODE) -> dict:
    return {
        "doc_code": code,
        "revision": revision,
        "revision_date": date,
        "stamp_status": "OK",
    }


@pytest.fixture()
def connection(tmp_path):
    conn = database.init_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


def test_hash_same_content_same_hash(tmp_path):
    first = make_file(tmp_path, "a.docx", b"content")
    second = make_file(tmp_path, "b.docx", b"content")
    assert calculate_sha256(first) == calculate_sha256(second)


def test_hash_different_content_different_hash(tmp_path):
    first = make_file(tmp_path, "a.docx", b"content 1")
    second = make_file(tmp_path, "b.docx", b"content 2")
    assert calculate_sha256(first) != calculate_sha256(second)


def test_hash_of_large_file_read_in_chunks(tmp_path):
    import hashlib

    data = b"x" * (8192 * 3 + 5)
    path = make_file(tmp_path, "big.bin", data)
    assert calculate_sha256(path) == hashlib.sha256(data).hexdigest()


def test_variant_group_ignores_case_and_spaces():
    assert compute_variant_group(f" {CODE.lower()} ", "1", "2025-08-01") == compute_variant_group(
        CODE, "1", "2025-08-01"
    )
    assert compute_variant_group(CODE, "1", "2025-08-01") != compute_variant_group(
        CODE, "2", "2025-08-01"
    )


def test_scenario_new(tmp_path, connection):
    path = make_file(tmp_path, "a.docx", b"v0")
    result = process_file_entry(path, connection, stamp=stamp("0"))
    assert result["result"] == RESULT_NEW
    assert result["is_current"] == 1
    assert len(database.list_files(connection)) == 1


def test_scenario_already_exists(tmp_path, connection):
    path = make_file(tmp_path, "a.docx", b"v0")
    process_file_entry(path, connection, stamp=stamp("0"))
    result = process_file_entry(path, connection, stamp=stamp("0"))
    assert result["result"] == RESULT_ALREADY_EXISTS
    assert len(database.list_files(connection)) == 1


def test_already_exists_for_copy_in_other_folder(tmp_path, connection):
    other = tmp_path / "other"
    other.mkdir()
    first = make_file(tmp_path, "a.docx", b"v0")
    copy = make_file(other, "a.docx", b"v0")
    process_file_entry(first, connection, stamp=stamp("0"))
    result = process_file_entry(copy, connection, stamp=stamp("0"))
    assert result["result"] == RESULT_ALREADY_EXISTS


def test_scenario_new_version_switches_current(tmp_path, connection):
    old = make_file(tmp_path, "a.docx", b"v0")
    new = make_file(tmp_path, "a_1.docx", b"v1")
    first = process_file_entry(old, connection, stamp=stamp("0", "2025-01-01"))
    second = process_file_entry(new, connection, stamp=stamp("1", "2025-08-01"))
    assert second["result"] == RESULT_NEW_VERSION
    assert second["is_current"] == 1
    assert database.get_file_by_id(connection, first["file_id"])["is_current"] == 0


def test_scenario_new_variant_keeps_both_current(tmp_path, connection):
    first_path = make_file(tmp_path, "a.docx", b"variant A")
    second_path = make_file(tmp_path, "b.docx", b"variant B")
    first = process_file_entry(first_path, connection, stamp=stamp("1"))
    second = process_file_entry(second_path, connection, stamp=stamp("1"))
    assert second["result"] == RESULT_NEW_VARIANT
    assert second["variant_group"] == first["variant_group"]
    rows = database.list_files(connection, only_current=True)
    assert len(rows) == 2


def test_file_without_doc_code_is_not_duplicated(tmp_path, connection):
    path = make_file(tmp_path, "a.docx", b"no stamp")
    empty = {"doc_code": "", "revision": "0", "revision_date": None, "stamp_status": "MISSING"}
    assert process_file_entry(path, connection, stamp=empty)["result"] == RESULT_NEW
    assert process_file_entry(path, connection, stamp=empty)["result"] == RESULT_ALREADY_EXISTS
    assert len(database.list_files(connection)) == 1
