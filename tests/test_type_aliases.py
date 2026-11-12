import os

from core import config
from core.search.scanner import scan_files


def test_aliases_saved_and_normalized(tmp_path):
    path = str(tmp_path / "c.json")
    saved = config.save_config(
        {
            "known_types": ["ВОР", "СО"],
            "type_aliases": {"ВОР": ["Ведомость", "ведомость", "вор", " "], "КЖ": ["x"], "СО": "bad"},
            "search_by_type": True,
        },
        path,
    )
    assert saved["type_aliases"] == {"ВОР": ["Ведомость", "ведомость"]}
    assert saved["search_by_type"] is True


def test_search_words(tmp_path):
    settings = {
        "known_types": ["ВОР", "СО"],
        "type_aliases": {"ВОР": ["Ведомость", "вор"]},
        "search_by_type": True,
    }
    assert config.search_words(settings) == ["ВОР", "Ведомость", "СО"]
    assert config.search_words({**settings, "search_by_type": False}) == []


def test_scan_filters_by_name_words(tmp_path):
    for name in ("a_ВОР.docx", "ведомость объёмов.doc", "План.docx", "~$ВОР.docx"):
        (tmp_path / name).write_bytes(b"x")
    found = sorted(p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in scan_files([str(tmp_path)], "*", name_words=["вор", "Ведомость"]))
    assert found == ["a_ВОР.docx", "ведомость объёмов.doc"]
    assert len(list(scan_files([str(tmp_path)], "*", name_words=[]))) == 3


def test_scan_name_words_whole_word(tmp_path):
    names = ("X.СВОР1.docx", "ЕСТ-1-АСДУ.ВОР.docx", "05_СО.doc", "Содержание тома.docx", "ЕСТ-Р-1-СОС_РД.docx", "КСОБ.doc")
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    found = sorted(os.path.basename(p) for p in scan_files([str(tmp_path)], "*", name_words=["СО", "ВОР", "СВОР"]))
    assert found == ["05_СО.doc", "X.СВОР1.docx", "ЕСТ-1-АСДУ.ВОР.docx"]
