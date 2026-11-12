import pytest

from core.doc_types import doc_type_from_name
from core.doc_types import (
    CABLE_LOG,
    SPEC,
    SVOR,
    UNKNOWN,
    VOR,
    normalize_doc_type,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ВОР", VOR),
        ("СВОР", SVOR),
        ("СО", SPEC),
        ("С", SPEC),
        ("с", SPEC),
        (" кж ", CABLE_LOG),
        ("", UNKNOWN),
        (None, UNKNOWN),
        ("XN", "XN"),
        ("ЭЭ", "ЭЭ"),
    ],
)
def test_normalize_doc_type(raw, expected):
    assert normalize_doc_type(raw) == expected


def test_svor_is_not_vor():
    assert normalize_doc_type("СВОР") != normalize_doc_type("ВОР")


def test_doc_type_from_name():
    assert doc_type_from_name('Кабельный журнал') == 'КЖ'
    assert doc_type_from_name('  кабельный   ЖУРНАЛ ЭС1') == 'КЖ'
    assert doc_type_from_name('Спецификация') is None
    assert doc_type_from_name(None) is None
