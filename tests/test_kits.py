"""Комплекты: шифр и изм. из пути, проверка при «Сохранить», kit_forced."""

import json

from api.controller import Controller
from core import database, kits

ROOT = "C:\\РД\\"


def row(path, doc_code, revision="1", meta=None, file_id=1, date="2026-06-01"):
    return {
        "id": file_id,
        "path": path,
        "doc_code": doc_code,
        "revision": revision,
        "revision_date": date,
        "meta_json": json.dumps(meta or {}),
    }


def test_folder_kit_with_change_folder():
    kit = kits.folder_kit(ROOT + "ЕСТ-ПМ-80825-Р-1-АГПП\\ИЗМ1 - согласован\\Ред. формат\\ВОР.docx")
    assert kit["code"] == "ЕСТ-ПМ-80825-Р-1-АГПП"
    assert kit["revision"] == 1


def test_folder_kit_variants_and_book_folder():
    assert kits.folder_kit(ROOT + "ЕСТ-ПМ-80825-Р-1-АСДУ\\Изм. 0\\Книга 2\\a.docx")["revision"] == 0
    assert kits.folder_kit(ROOT + "ЕСТ-ПМ-80825-Р-1-АСДУ\\ИЗМ2\\Книга 1\\a.docx")["revision"] == 2


def test_folder_kit_without_change_folder_is_zero():
    kit = kits.folder_kit(ROOT + "ЕСТ-ПМ-80825-Р-1-ГГ\\Ред. формат\\a.docx")
    assert kit["revision"] == 0 and kit["code"] == "ЕСТ-ПМ-80825-Р-1-ГГ"


def test_folder_kit_outside_structure():
    assert kits.folder_kit("C:\\ВОР\\a.docx") is None


def test_kit_info_ok_and_date_from_stamp():
    info = kits.kit_info(
        row(ROOT + "ЕСТ-ПМ-80825-Р-1-АЭК\\ИЗМ1\\a.docx", "ЕСТ-ПМ-80825-Р-1-АЭК.ВОР",
            meta={"stamp_date": "2026-06-01"}, date="2026-07-01")
    )
    assert info["kit_problem"] == ""
    assert (info["kit_code"], info["kit_revision"], info["kit_date"]) == (
        "ЕСТ-ПМ-80825-Р-1-АЭК", 1, "2026-06-01")


def test_stamp_code_differs_from_folder_is_problem():
    info = kits.kit_info(row(ROOT + "ЕСТ-ПМ-80825-Р-1-ЭК\\ИЗМ1\\a.docx", "ЕСТ-ПМ-80825-Р-1-АСТУЭ.ВОР"))
    assert "шифр" in info["kit_problem"]
    assert info["kit_code"] == "ЕСТ-ПМ-80825-Р-1-ЭК"  # шифр задаёт папка


def test_revision_differs_from_folder_is_problem():
    info = kits.kit_info(row(ROOT + "ЕСТ-ПМ-80825-Р-1-ЭК\\ИЗМ1\\a.docx", "ЕСТ-ПМ-80825-Р-1-ЭК.ВОР", "0"))
    assert "изм." in info["kit_problem"]


def test_check_catches_foreign_document():
    ok = row(ROOT + "ЕСТ-ПМ-80825-Р-1-ЛВС\\ИЗМ1\\b.docx", "ЕСТ-ПМ-80825-Р-1-ЛВС.ВОР", file_id=1)
    foreign = row(ROOT + "ЕСТ-ПМ-80825-Р-1-ЛВС\\ИЗМ1\\c.docx", "ЕСТ-ПМ-80825-Р-1-АСТУЭ.ВОР", file_id=2)
    conflicts = kits.check_kits([ok, foreign])
    assert [c["id"] for c in conflicts] == [2]


def test_forced_document_is_not_checked_again():
    foreign = row(ROOT + "ЕСТ-ПМ-80825-Р-1-ЛВС\\ИЗМ1\\c.docx", "ЕСТ-ПМ-80825-Р-1-АСТУЭ.ВОР",
                  meta={"kit_forced": True})
    assert kits.check_kits([foreign]) == []
    assert kits.kit_info(foreign)["kit_forced"] is True


def test_first_document_defines_kit_outside_structure():
    first = row("C:\\ВОР\\a.docx", "ЕСТ-ПМ-80825-Р-1-ЭК.ВОР", file_id=1)
    same = row("C:\\ВОР\\b.docx", "ЕСТ-ПМ-80825-Р-1-ЭК.СВОР", file_id=2)
    other = row("C:\\ВОР\\c.docx", "ЕСТ-ПМ-80825-Р-1-АПС.ВОР", file_id=3)
    other_dir = row("C:\\Другая\\d.docx", "ЕСТ-ПМ-80825-Р-1-АПС.ВОР", file_id=4)
    assert [c["id"] for c in kits.check_kits([first, same, other, other_dir])] == [3]


def test_controller_check_and_force(tmp_path):
    db = str(tmp_path / "app.db")
    path = str(tmp_path / "ЕСТ-ПМ-80825-Р-1-ЛВС" / "ИЗМ1" / "c.docx")
    connection = database.init_db(db)
    file_id = database.add_file(
        connection, "h1", path, "c.docx",
        stamp={"doc_code": "ЕСТ-ПМ-80825-Р-1-АСТУЭ.ВОР", "revision": "1", "revision_date": "2026-06-01",
               "stamp_date": "2026-06-01", "revision_date_source": "stamp"},
    )
    connection.close()
    controller = Controller(db_path=db)
    assert [c["id"] for c in controller.check_kits([file_id])["conflicts"]] == [file_id]
    controller.process_selected([file_id], [file_id])
    controller.tasks.wait(5)
    files = controller.get_files()["files"]
    assert files[0]["kit_forced"] is True
    assert controller.check_kits([file_id])["conflicts"] == []
