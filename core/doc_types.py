"""Реестр типов документов: единая точка для ВОР, СВОР, СО, КЖ.

Тип из штампа приводится к каноническому виду (`normalize_doc_type`).
Дальше по этому типу выбираются правила чистки шапки и канонические
колонки (добавляются в следующих шагах Этапа 2).
"""

from __future__ import annotations

VOR = "ВОР"
SVOR = "СВОР"
SPEC = "СО"
CABLE_LOG = "КЖ"
UNKNOWN = "XN"  # шифр без типа документа

# Тип из штампа -> канонический тип. `С` — та же спецификация, что и `СО`.
DOC_TYPE_ALIASES: dict[str, str] = {
    "ВОР": VOR,
    "СВОР": SVOR,
    "СО": SPEC,
    "С": SPEC,
    "КЖ": CABLE_LOG,
}

# Типы с собственной схемой обработки.
KNOWN_DOC_TYPES: tuple[str, ...] = (VOR, SVOR, SPEC, CABLE_LOG)


# Признак типа в поле штампа «Наименование документа» (нижний регистр).
DOC_NAME_MARKERS: tuple[tuple[str, str], ...] = (
    ("кабельный журнал", CABLE_LOG),
)


def doc_type_from_name(document_name: str | None) -> str | None:
    """Тип по наименованию документа из штампа; None, если признака нет."""
    text = " ".join((document_name or "").lower().split())
    for marker, doc_type in DOC_NAME_MARKERS:
        if marker in text:
            return doc_type
    return None


def normalize_doc_type(raw: str | None) -> str:
    """Каноническое имя типа. Неизвестные типы возвращаются как есть (верхний регистр)."""
    value = (raw or "").strip().upper()
    if not value:
        return UNKNOWN
    return DOC_TYPE_ALIASES.get(value, value)
