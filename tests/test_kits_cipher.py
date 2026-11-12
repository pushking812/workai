from core.kits import check_kits, cipher_key, kit_info


def _row(path, code, rev=0):
    return {"id": 1, "path": path, "doc_code": code, "revision": str(rev), "meta_json": "{}"}


def test_cipher_key_ignores_stage_marker():
    assert cipher_key("ЕСТ-ПМ-80825-1-АСДУ-ОСУ") == cipher_key("ЕСТ-ПМ-80825-Р-1-АСДУ-ОСУ")
    assert cipher_key("ЕСТ-ПМ-80825-1-АСДУ.ВОР") == cipher_key("ЕСТ-ПМ-80825-Р-1-АСДУ")


def test_missing_stage_marker_is_not_a_problem():
    row = _row("ЕСТ-ПМ-80825-Р-1-АСДУ/ИЗМ0/a.docx", "ЕСТ-ПМ-80825-1-АСДУ.ВОР")
    assert kit_info(row)["kit_problem"] == ""
    assert check_kits([row]) == []


def test_other_cipher_still_a_problem():
    row = _row("ЕСТ-ПМ-80825-Р-1-АСДУ/ИЗМ0/a.docx", "ЕСТ-ПМ-80825-Р-1-АСТУЭ.ВОР")
    assert kit_info(row)["kit_problem"]
