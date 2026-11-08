"""Профили шапок таблиц и очистка колонок (Этап 1.3).

По аналогии со штампами (`detect_stamp_profile`) шапка сначала получает
профиль, а затем колонки чистятся по правилам профиля.

Профили кабельного журнала (КЖ):
* `cable_basic`   — 9–10 колонок: обозначение, трасса, кабель (по проекту / проложен);
* `cable_section` — 11 колонок: добавлен «Участок трассы кабеля» (дважды: до и
  после «по проекту»);
* `cable_pipes`   — 17 колонок: «Проход через» (труба, протяжной ящик) и бирки.

Колонки блока «Проложен» (в `cable_section` вместе со вторым «Участком трассы
кабеля») — заготовка для заполнения по факту. Блок не используется и
не выгружается никогда, даже если в нём есть данные.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.parsers.docx_parser import LEVEL_SEPARATOR, HeaderScan, join_levels, scan_headers
from core.transformer.schema_analyzer import normalize_header

PROFILE_GENERIC = "generic"  # плоская шапка (ВОР, спецификации)
PROFILE_CABLE_BASIC = "cable_basic"
PROFILE_CABLE_SECTION = "cable_section"
PROFILE_CABLE_PIPES = "cable_pipes"
PROFILE_UNKNOWN = "unknown"  # иерархическая шапка, но не кабельный журнал

CABLE_PROFILES = (PROFILE_CABLE_BASIC, PROFILE_CABLE_SECTION, PROFILE_CABLE_PIPES)

# Ключевые имена строятся той же нормализацией, что и заголовки: правило
# усечения длинных названий не должно ломать определение профиля.
_CABLE_FIRST_COLUMN = normalize_header("Обозначение кабеля, провода").casefold()
_ROUTE_GROUP = normalize_header("Трасса").casefold()
_PIPES_GROUP = normalize_header("Проход через").casefold()
_SECTION_COLUMN = normalize_header("Участок трассы кабеля").casefold()
_FACT_GROUP = normalize_header("Проложен").casefold()


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[list[str]]
    profile: str
    hierarchical: bool
    # Пропущенные колонки: [(имя, причина)].
    dropped: list[tuple[str, str]] = field(default_factory=list)


def detect_header_profile(headers: list[str], hierarchical: bool) -> str:
    """Профиль по набору колонок (имена уже нормализованы и склеены через `|`)."""
    if not hierarchical:
        return PROFILE_GENERIC
    paths = [header.casefold().split(LEVEL_SEPARATOR) for header in headers]
    is_cable = (
        bool(paths)
        and paths[0] == [_CABLE_FIRST_COLUMN]
        and any(path[0] == _ROUTE_GROUP and len(path) > 1 for path in paths)
    )
    if not is_cable:
        return PROFILE_UNKNOWN
    if any(path[0] == _PIPES_GROUP for path in paths):
        return PROFILE_CABLE_PIPES
    if any(path == [_SECTION_COLUMN] for path in paths):
        return PROFILE_CABLE_SECTION
    return PROFILE_CABLE_BASIC


def _is_section_row(row: list[str]) -> bool:
    """Строка-раздел: все заполненные ячейки одинаковы («КЛ-6кВ» в каждой колонке)."""
    return len({cell for cell in row if cell}) == 1


def _fact_columns(headers: list[str]) -> list[int]:
    paths = [header.casefold().split(LEVEL_SEPARATOR) for header in headers]
    fact = [index for index, path in enumerate(paths) if _FACT_GROUP in path]
    if not fact:
        return []
    first = fact[0]
    # Второй «Участок трассы кабеля» перед блоком «Проложен» — часть заготовки.
    if first > 0 and headers[first - 1].casefold() in {h.casefold() for h in headers[: first - 1]}:
        fact.insert(0, first - 1)
    return fact


def parse_table(table: list[list[str]]) -> ParsedTable:
    """Шапка, профиль и строки данных без лишних колонок.

    Плоские таблицы (ВОР) возвращаются как есть: `generic`, строки от
    `data_start`. Для иерархических шапок выбрасываются пустые колонки-артефакты
    и блок «Проложен» (всегда), пустые строки данных удаляются.
    """
    scan: HeaderScan = scan_headers(table)
    headers = [join_levels(scan, index) for index in range(scan.width)]
    profile = detect_header_profile(headers, scan.hierarchical)
    data = table[scan.data_start :]
    if not scan.hierarchical:
        return ParsedTable(headers, data, profile, False)

    width = scan.width
    data = [list(row) + [""] * (width - len(row)) for row in data if any(row)]
    values = [row for row in data if not _is_section_row(row)]

    def is_empty(index: int) -> bool:
        return not any(row[index] for row in values)

    drop: dict[int, str] = {}
    if profile in CABLE_PROFILES:
        fact = _fact_columns(headers)
        # Блок не используется, даже если в нём есть данные (решение пользователя).
        for index in fact:
            drop[index] = "заготовка по факту, не используется"
    for index in range(width):
        if index not in drop and scan.is_orphan(index) and is_empty(index):
            drop[index] = "лишняя пустая колонка"

    keep = [index for index in range(width) if index not in drop]
    return ParsedTable(
        [headers[index] for index in keep],
        [[row[index] for index in keep] for row in data],
        profile,
        True,
        [(headers[index] or "(без названия)", reason) for index, reason in sorted(drop.items())],
    )
