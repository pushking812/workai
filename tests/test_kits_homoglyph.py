from core.kits import cipher_key


def test_latin_homoglyphs_equal_cyrillic():
    assert cipher_key('ЕСТ-ПМ-80825-Р-1-ЭС1') == cipher_key('ECT-ПМ-80825-P-1-ЭC1')
    assert cipher_key('ЕСТ-ПМ-80825-Р-1-ЭС1') != cipher_key('ЕСТ-ПМ-80825-Р-1-ЭС2')
