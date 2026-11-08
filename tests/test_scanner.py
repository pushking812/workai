import os

from core.search.scanner import scan_files
from core.statuses import FileStatus, UiStatus, is_db_status


def _touch(root, *parts):
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x")
    return path


def _names(paths):
    return sorted(os.path.basename(path) for path in paths)


def test_mask_and_extensions(tmp_path):
    root = str(tmp_path)
    _touch(root, "a_ВОР.docx")
    _touch(root, "sub", "b_вор_2.DOCX")
    _touch(root, "old.ВОР.doc")
    _touch(root, "spec.docx")
    _touch(root, "ВОР.txt")
    assert _names(scan_files([root], "*ВОР*")) == ["a_ВОР.docx", "b_вор_2.DOCX", "old.ВОР.doc"]


def test_skips_hidden_and_temp(tmp_path):
    root = str(tmp_path)
    _touch(root, "~$ВОР.docx")
    _touch(root, ".git", "ВОР.docx")
    _touch(root, "ok", "ВОР.docx")
    found = list(scan_files([root], "*ВОР*"))
    assert len(found) == 1 and ".git" not in found[0]


def test_duplicate_directories_and_missing(tmp_path):
    root = str(tmp_path)
    _touch(root, "ВОР.docx")
    found = list(scan_files([root, root, os.path.join(root, "нет")], "*"))
    assert len(found) == 1


def test_is_generator_and_stop(tmp_path):
    root = str(tmp_path)
    for index in range(5):
        _touch(root, f"f{index}.docx")
    gen = scan_files([root], "*")
    assert iter(gen) is gen
    flag = {"stop": False}
    got = []
    for path in scan_files([root], "*", should_stop=lambda: flag["stop"]):
        got.append(path)
        flag["stop"] = True
    assert len(got) == 1


def test_statuses():
    assert is_db_status("READY") and not is_db_status("FOUND")
    assert {s.value for s in FileStatus} == {"SAVED", "PROCESSING", "NEEDS_MAPPING", "READY", "ERROR"}
    assert UiStatus.FOUND.value == "FOUND"
