from core.search.scanner import normalize_lookalikes, scan_files


def test_normalize_lookalikes():
    assert normalize_lookalikes("Cпецификация") == "Спецификация"


def test_scan_finds_latin_c_in_name_and_folder(tmp_path):
    folder = tmp_path / "Изм1 - Cогласован"
    folder.mkdir()
    (folder / "20. Cпецификация.docx").write_bytes(b"x")
    found = list(scan_files(
        [str(tmp_path)], name_words=["Спецификация"], folder_filters=["Изм1"],
    ))
    assert len(found) == 1
    found = list(scan_files(
        [str(tmp_path)], name_words=["Cпецификация"], folder_filters=["Изм1 - Согласован"],
    ))
    assert len(found) == 1
