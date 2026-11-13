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

import re
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
    # Шифры документов по стадиям из шапки СВОР: {"П": "...", "Р": "..."}.
    stage_codes: dict[str, str] = field(default_factory=dict)
    # Все шапки до отбрасывания колонок и индексы оставленных (для продолжений таблицы).
    all_headers: list[str] = field(default_factory=list)
    keep: list[int] = field(default_factory=list)
    # Подозрительные значения `№ п/п` (скобки и т.п.): признак сбоя разбора.
    number_issues: list[str] = field(default_factory=list)


# «Кол-во (стадия П) ЕСТ-ПМ-80825-1-ИОС2.2.ВОР»: имя, стадия, шифр документа.
# Стадия: кириллическая П/Р (латинскую P считаем русской Р).
_STAGE_QTY_RE = re.compile(
    r"^\s*кол-?во\s*"
    r"(?:\(\s*стадия\s*(?P<s1>[ПР])(?P<q1>[^)]*)\)"  # (стадия Р) / (стадия Р изм.1)
    r"|по\s+(?P<s2>[ПР])Д\s*(?:\((?P<q2>[^)]*)\))?)"  # По РД (изм. 2)
    r"\s*(?P<code>.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def split_stage_header(header: str) -> tuple[str, str, str]:
    """`Кол-во (стадия П) <шифр>` -> (`Кол-во (стадия П)`, `П`, `<шифр>`).

    Шифр документа в имя колонки не входит: он относится к файлу, а не к
    колонке. Стадия остаётся в имени, иначе колонки П и Р совпали бы.
    Варианты записи `(стадия Р изм.1) <шифр>` и `По РД (изм. 2) <шифр>`
    приводятся к тому же имени; пометка об изменении остаётся при шифре:
    `<шифр> (изм.1)`. Для остальных заголовков возвращается (заголовок, "", "").
    """
    match = _STAGE_QTY_RE.match(header or "")
    if not match:
        return header, "", ""
    stage = (match.group("s1") or match.group("s2")).upper().replace("P", "Р")
    note = re.sub(r"\s+", " ", (match.group("q1") or match.group("q2") or "")).strip()
    code = match.group("code")
    if note:
        code = ("%s (%s)" % (code, note)).strip()
    return "Кол-во (стадия %s)" % stage, stage, code


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


_NOT_NUMBER_CHARS = re.compile(r"[^0-9.]")
NUMBER_HEADERS = {"NПП", "N"}


def clean_row_numbers(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    """Значения `№ п/п` не правятся: скобка в номере — признак сбоя разбора,
    цифра при этом уже неверна, «починка» скрыла бы ошибку (см. `suspect_row_numbers`)."""
    return rows


def suspect_row_numbers(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Значения колонки `№ п/п` с символами кроме цифр и точек (например `18)`)."""
    columns = [i for i, h in enumerate(headers) if normalize_header(h) in NUMBER_HEADERS]
    found: list[str] = []
    for row in rows:
        for i in columns:
            value = row[i] if i < len(row) else ""
            # Только числа с лишними знаками; текстовые строки разделов не в счёт.
            if re.search(r"\d", value) and _NOT_NUMBER_CHARS.search(value) and value not in found:
                found.append(row[i])
    return found


_NUMBER_TOKEN_RE = re.compile(r"\d[\d.]*")
_POSITION_HEADERS = {"nпп", "пп", "n", "поз"}


def _split_name_number(name: str) -> tuple[str, str] | None:
    """«1. 2. Кабель» → («1.2», «Кабель»); первое слово не номер → None.

    Номер — слово из цифр и точек. Если слово кончается точкой, а следующее тоже
    номер (`1. 2.`), они склеиваются."""
    words = name.split()
    if not words or not _NUMBER_TOKEN_RE.fullmatch(words[0]):
        return None
    number, used = words[0], 1
    while used < len(words) and number.endswith(".") and _NUMBER_TOKEN_RE.fullmatch(words[used]):
        number += words[used]
        used += 1
    return number.rstrip("."), " ".join(words[used:])


NUMBERED_NAMES_SHARE = 0.75  # доля наименований с номером в начале (анализ СО: 84–95 % у нумерованных, 0 % у остальных)


def _names_are_numbered(rows: list[list[str]], name_col: int) -> bool:
    """Нумерация есть, если не меньше `NUMBERED_NAMES_SHARE` непустых наименований
    начинаются с номера (остальные — переносы строк и заголовки разделов)."""
    names = [row[name_col].strip() for row in rows if name_col < len(row) and row[name_col].strip()]
    if not names:
        return False
    numbered = sum(1 for n in names if _split_name_number(n) is not None)
    return numbered / len(names) >= NUMBERED_NAMES_SHARE


def _number_parts(value: str) -> tuple[int, ...] | None:
    """«2.37» → (2, 37); не номер → None."""
    text = value.strip().rstrip(".")
    if not re.fullmatch(r"\d+(\.\d+)*", text):
        return None
    return tuple(int(p) for p in text.split("."))


def _follows(prev: tuple[int, ...], cur: tuple[int, ...]) -> bool:
    """`cur` продолжает нумерацию после `prev`: сосед (2.37→2.38), первый
    вложенный (2→2.1) или следующий номер выше уровнем (2.45→3)."""
    if cur == prev[:-1] + (prev[-1] + 1,) or cur == prev + (1,):
        return True
    return any(cur == prev[: k - 1] + (prev[k - 1] + 1,) for k in range(1, len(prev)))


def _row_sequence(rows: list[list[str]], num_col: int, name_col: int) -> list[tuple[int, ...] | None]:
    """Номер каждой строки: из колонки номера, иначе из начала наименования."""
    result = []
    for row in rows:
        parts = _number_parts(row[num_col]) if num_col < len(row) else None
        if parts is None and name_col < len(row):
            split = _split_name_number(row[name_col])
            parts = _number_parts(split[0]) if split else None
        result.append(parts)
    return result


def _fits_sequence(seq: list[tuple[int, ...] | None], index: int) -> bool:
    """Номер строки `index` вписывается в нумерацию соседей (ближайших сверху и снизу)."""
    cur = seq[index]
    if cur is None:
        return False
    prev = next((seq[j] for j in range(index - 1, -1, -1) if seq[j] is not None), None)
    nxt = next((seq[j] for j in range(index + 1, len(seq)) if seq[j] is not None), None)
    if prev is None and nxt is None:
        return True
    # Повтор пункта для разных участков (14.1, 14.1, 14.1) тоже вписывается.
    if cur in (prev, nxt):
        return True
    return bool((prev and _follows(prev, cur)) or (nxt and _follows(cur, nxt)))


def merge_wrapped_names(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    """Наименование, разбитое на две строки таблицы, склеивается в одну.

    Перенос — строка без номера, где заполнено только наименование; перед ней
    стоит пункт с данными, а следующий пронумерованный пункт продолжает нумерацию
    предыдущего (2.37 → 2.38). Раздел с номером (`3. Кабели`) переносом не считается."""
    folded = [normalize_header(h).casefold() for h in headers]
    num_col = next((i for i, h in enumerate(folded) if h in _POSITION_HEADERS), None)
    name_col = next((i for i, h in enumerate(headers) if h.casefold().startswith("наименование")), None)
    if num_col is None or name_col is None or num_col == name_col:
        return rows
    seq = [_number_parts(r[num_col]) if num_col < len(r) else None for r in rows]
    if sum(1 for s in seq if s) / max(1, sum(1 for r in rows if any(c.strip() for c in r))) < NUMBERED_NAMES_SHARE:
        return rows
    result: list[list[str]] = []
    result_seq: list[tuple[int, ...] | None] = []
    for i, row in enumerate(rows):
        row = list(row)
        only_name = (
            name_col < len(row)
            and row[name_col].strip()
            and not any(c.strip() for k, c in enumerate(row) if k != name_col)
        )
        if only_name and result and result_seq[-1] is not None:
            prev_row = result[-1]
            has_data = any(c.strip() for k, c in enumerate(prev_row) if k not in (num_col, name_col))
            nxt = next((s for s in seq[i + 1 :] if s is not None), None)
            if has_data and nxt is not None and _follows(result_seq[-1], nxt):
                prev_row[name_col] = (prev_row[name_col].rstrip() + " " + row[name_col].strip()).strip()
                continue
        result.append(row)
        result_seq.append(seq[i])
    return result


def move_name_numbers(headers: list[str], rows: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    """Номер пункта в начале наименования переносится в колонку номера (если она пуста).

    Если в колонке номера стоит текст, а в наименовании номер, переносить некуда:
    значение остаётся, а текст попадает в список подозрительных."""
    folded = [normalize_header(h).casefold() for h in headers]
    num_col = next((i for i, h in enumerate(folded) if h in _POSITION_HEADERS), None)
    name_col = next((i for i, h in enumerate(headers) if h.casefold().startswith("наименование")), None)
    if num_col is None or name_col is None or num_col == name_col:
        return rows, []
    if not _names_are_numbered(rows, name_col):
        return rows, []
    issues: list[str] = []
    result = []
    seq = _row_sequence(rows, num_col, name_col)
    for index, row in enumerate(rows):
        row = list(row)
        split = _split_name_number(row[name_col]) if name_col < len(row) else None
        # Номер, не вписывающийся в нумерацию соседей (`100 шт`), остаётся в наименовании.
        if split is not None and not _fits_sequence(seq, index):
            split = None
        if split is not None and num_col < len(row):
            current = row[num_col].strip()
            if not current:
                row[num_col], row[name_col] = split
            elif not re.fullmatch(r"[\d.]+", current) and current not in issues:
                issues.append(current)
        result.append(row)
    return result, issues


def fill_repeated_numbers(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    """Пустой номер + номер в начале наименования, равный номеру ближайшей строки
    сверху или снизу с номером в колонке: номер переносится в колонку (повтор пункта
    для разных участков, `14.1 Кабель…` рядом с `NПП` = `14.1`). Порог долей не нужен."""
    folded = [normalize_header(h).casefold() for h in headers]
    num_col = next((i for i, h in enumerate(folded) if h in _POSITION_HEADERS), None)
    name_col = next((i for i, h in enumerate(headers) if h.casefold().startswith("наименование")), None)
    if num_col is None or name_col is None or num_col == name_col:
        return rows
    col_seq = [_number_parts(r[num_col]) if num_col < len(r) else None for r in rows]
    result = []
    for index, row in enumerate(rows):
        row = list(row)
        if num_col < len(row) and name_col < len(row) and not row[num_col].strip():
            split = _split_name_number(row[name_col])
            parts = _number_parts(split[0]) if split else None
            if parts is not None:
                prev = next((col_seq[j] for j in range(index - 1, -1, -1) if col_seq[j] is not None), None)
                nxt = next((col_seq[j] for j in range(index + 1, len(rows)) if col_seq[j] is not None), None)
                if parts in (prev, nxt):
                    row[num_col], row[name_col] = split
        result.append(row)
    return result


def parse_table(table: list[list[str]], like: "ParsedTable | None" = None) -> ParsedTable:
    """См. `_parse_table`; дополнительно заполняет `number_issues`."""
    parsed = _parse_table(table, like)
    conflicts: list[str] = []
    if not parsed.hierarchical:
        parsed.rows = fill_repeated_numbers(parsed.headers, parsed.rows)
        parsed.rows, conflicts = move_name_numbers(parsed.headers, parsed.rows)
        parsed.rows = merge_wrapped_names(parsed.headers, parsed.rows)
    found = suspect_row_numbers(parsed.headers, parsed.rows)
    parsed.number_issues = found + [c for c in conflicts if c not in found]
    return parsed


def _parse_table(table: list[list[str]], like: "ParsedTable | None" = None) -> ParsedTable:
    """Шапка, профиль и строки данных без лишних колонок.

    `like` — первая таблица документа с шапкой. Продолжение без шапки той же
    ширины получает её шапку и те же колонки, а не режет колонки по своим данным.

    Плоские таблицы (ВОР) возвращаются как есть: `generic`, строки от
    `data_start`. Для иерархических шапок выбрасываются пустые колонки-артефакты
    и блок «Проложен» (всегда), пустые строки данных удаляются.
    """
    scan: HeaderScan = scan_headers(table)
    headers = [join_levels(scan, index) for index in range(scan.width)]
    profile = detect_header_profile(headers, scan.hierarchical)
    data = table[scan.data_start :]
    if not scan.hierarchical:
        stage_codes: dict[str, str] = {}
        for index, header in enumerate(headers):
            headers[index], stage, code = split_stage_header(header)
            if stage and code:
                stage_codes[stage] = code
        # Колонка без названия отбрасывается, если она пуста или лишь повторяет
        # соседнюю слева (растянутая ячейка в строке данных).
        width = scan.width
        data = [list(row) + [""] * (width - len(row)) for row in data]
        like_width = len(like.all_headers) if like is not None else 0
        # Часть строк продолжения может содержать лишние пустые ячейки справа
        # (в .doc строка из 10 ячеек среди строк из 9): ширина таблицы больше
        # шапки, но лишние колонки пусты — это то же продолжение.
        extra_empty = width > like_width and all(
            not (row[index] or "").strip()
            for row in data
            for index in range(like_width, width)
        )
        if (
            like is not None
            and not any(h.strip() for h in headers)
            and like.all_headers
            and (width == like_width or extra_empty)
        ):
            data = [row[:like_width] for row in data]
            keep = list(like.keep)
            kept_headers = [like.all_headers[index] for index in keep]
            return ParsedTable(
                kept_headers,
                clean_row_numbers(kept_headers, [[row[index] for index in keep] for row in data]),
                like.profile,
                False,
                [],
                stage_codes={},
                all_headers=list(like.all_headers),
                keep=keep,
            )
        empty = [
            index
            for index in range(width)
            if not headers[index].strip()
            and all(not row[index].strip() or (index > 0 and row[index] == row[index - 1]) for row in data)
        ]
        keep = [index for index in range(width) if index not in empty]
        kept_headers = [headers[index] for index in keep]
        return ParsedTable(
            kept_headers,
            clean_row_numbers(kept_headers, [[row[index] for index in keep] for row in data]),
            profile,
            False,
            [("(без названия)", "лишняя пустая колонка") for _ in empty],
            stage_codes=stage_codes,
            all_headers=list(headers),
            keep=keep,
        )

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
