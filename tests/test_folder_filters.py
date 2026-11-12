import os

from core import config
from core.search.scanner import scan_files


def _touch(root, *parts):
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x")
    return path


def _names(paths):
    return sorted(os.path.basename(path) for path in paths)


def _tree(root):
    _touch(root, "root.docx")
    _touch(root, "ИЗМ0", "Ред. формат", "a.docx")
    _touch(root, "ИЗМ0", "PDF", "b.docx")
    _touch(root, "ИЗМ1", "Ред.формат", "c.docx")
    _touch(root, "ИЗМ1", "d.docx")
    _touch(root, "Архив", "Ред. формат", "e.docx")
    _touch(root, "Ред. формат", "f.docx")


def test_no_filter_scans_everything(tmp_path):
    _tree(str(tmp_path))
    assert len(list(scan_files([str(tmp_path)]))) == 7
    assert len(list(scan_files([str(tmp_path)], folder_filters=[]))) == 7


def test_filter_applies_to_nested_folders_at_every_level(tmp_path):
    _tree(str(tmp_path))
    found = scan_files([str(tmp_path)], folder_filters=["Изм", "Ред. формат"])
    # b.docx (папка PDF) и e.docx (папка Архив) отброшены; файл в начальной папке остаётся
    assert _names(found) == ["a.docx", "c.docx", "d.docx", "f.docx", "root.docx"]


def test_filter_ignores_case_and_spaces(tmp_path):
    _tree(str(tmp_path))
    found = scan_files([str(tmp_path)], folder_filters=["изм1", "РЕД.ФОРМАТ"])
    assert _names(found) == ["c.docx", "d.docx", "f.docx", "root.docx"]


def test_filter_matches_only_folder_name_start(tmp_path):
    _touch(str(tmp_path), "ИЗМ1", "a.docx")
    _touch(str(tmp_path), "Старый ИЗМ1", "b.docx")
    _touch(str(tmp_path), "ИЗМ1 копия", "c.docx")
    found = scan_files([str(tmp_path)], folder_filters=["Изм"])
    assert _names(found) == ["a.docx", "c.docx"]


def test_filter_does_not_check_start_folder_name(tmp_path):
    start = tmp_path / "ЕСТ-ПМ-1-АГПП"
    _touch(str(start), "x.docx")
    _touch(str(start), "ИЗМ1", "y.docx")
    found = scan_files([str(start)], folder_filters=["Изм"])
    assert _names(found) == ["x.docx", "y.docx"]


def test_config_folder_filters_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    assert config.load_config(path)["folder_filters"] == ["Изм", "Ред. формат"]
    saved = config.save_config({"folder_filters": [" Изм0 ", "Изм0", "", "Ред.формат"]}, path)
    assert saved["folder_filters"] == ["Изм0", "Ред.формат"]
    assert config.save_config({"folder_filters": []}, path)["folder_filters"] == []
    assert config.load_config(path)["folder_filters"] == []
