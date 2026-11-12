"""Комплекты проектной документации: шифр проекта + номер изменения + дата.

Комплект лежит в отдельной папке: ``<корень>/<шифр>/[ИЗМ0|ИЗМ1 - ...]/Ред. формат``.
Шифр и номер изменения определяет путь (папка шифра и папка изменения);
если штамп документа им противоречит, файл помечается как проблемный.
Если папки изменения нет, это ИЗМ0. Вложенные папки (`Книга 1`, `Ред. формат`)
в ключ комплекта не входят. Дата комплекта — дата изменения из штампа
(`stamp_date`), дата документа — `revision_date`.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

# Папка шифра: ЕСТ-ПМ-80825-Р-1-АГПП (Р может быть кириллицей или латиницей).
_CIPHER_DIR_RE = re.compile(r"^[^\\/]+?-\d{3,}-[РPрp]-\d+-.+$")
# Папка изменения: ИЗМ0, Изм. 1, ИЗМ1 - согласован.
_CHANGE_DIR_RE = re.compile(r"^изм\.?\s*(\d+)(?:\D|$)", re.IGNORECASE)


def _split_path(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", path or "") if p]


def folder_kit(path: str) -> dict[str, Any] | None:
    """Комплект по пути файла: {'code', 'revision', 'dir'} или None, если папки шифра нет."""
    parts = _split_path(path)[:-1]  # без имени файла
    for index, name in enumerate(parts):
        if _CIPHER_DIR_RE.match(name):
            revision = 0
            kit_dir = parts[: index + 1]
            if index + 1 < len(parts):
                match = _CHANGE_DIR_RE.match(parts[index + 1])
                if match:
                    revision = int(match.group(1))
                    kit_dir = parts[: index + 2]
            return {"code": name, "revision": revision, "dir": os.sep.join(kit_dir)}
    return None


def doc_cipher(doc_code: str | None) -> str:
    """Шифр документа без типа (`.ВОР`), без пробелов, в верхнем регистре."""
    text = re.sub(r"\s+", "", doc_code or "")
    return text.rsplit(".", 1)[0].upper() if "." in text else text.upper()


_STAGE_RE = re.compile(r"-[РPрp]-(?=\d)")


# Латинские буквы, похожие на русские по начертанию, -> русские (в верхнем регистре).
_HOMOGLYPHS = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")


def fold_homoglyphs(text: str) -> str:
    """Заменяет латинские буквы похожего начертания на русские (регистр верхний)."""
    return (text or "").upper().translate(_HOMOGLYPHS)


def cipher_key(code: str | None) -> str:
    """Ключ сравнения шифров: без пробелов и типа, регистр верхний, `-Р-` не учитывается,
    латинские двойники русских букв (C, P, E, ...) приравниваются к русским."""
    return _STAGE_RE.sub("-", fold_homoglyphs(doc_cipher(code)))


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row.get("meta_json") or "{}")
    except ValueError:
        return {}


def kit_info(row: dict[str, Any]) -> dict[str, Any]:
    """Комплект документа: kit_code, kit_revision, kit_date, kit_problem, kit_forced.

    `kit_problem` — текст расхождения штампа с путём ('' если всё сходится).
    """
    meta = _meta(row)
    doc_rev = _to_int(row.get("revision"))
    folder = folder_kit(row.get("path") or "")
    stamp_cipher = doc_cipher(row.get("doc_code"))
    if folder:
        code, revision = folder["code"], folder["revision"]
    else:
        code, revision = stamp_cipher or "", doc_rev if doc_rev is not None else 0
    problems: list[str] = []
    if folder:
        if stamp_cipher and cipher_key(stamp_cipher) != cipher_key(folder["code"]):
            problems.append(f"шифр в штампе {stamp_cipher} ≠ папка {folder['code']}")
        if doc_rev is not None and doc_rev != folder["revision"]:
            problems.append(f"изм. в штампе {doc_rev} ≠ папка ИЗМ{folder['revision']}")
    path_problem = "; ".join(problems)
    issues = meta.get("number_issues")
    if issues:
        problems.append("сомнительные № п/п: " + ", ".join(str(v) for v in issues[:5]))
    return {
        "kit_path_problem": path_problem,
        "kit_code": code,
        "kit_revision": revision,
        "kit_date": meta.get("stamp_date") or row.get("revision_date") or "",
        "kit_problem": "; ".join(problems),
        "kit_forced": bool(meta.get("kit_forced")),
    }


def check_kits(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Проверка при «Сохранить»: документы, не принадлежащие комплекту.

    Файл в папке шифра сверяется с этой папкой. Файл вне такой структуры
    сверяется с первым документом своей папки (он и задаёт комплект).
    Уже принятые вручную (`kit_forced`) не проверяются. Возвращает список
    {'id', 'path', 'message'}.
    """
    conflicts: list[dict[str, Any]] = []
    first_in_dir: dict[str, dict[str, Any]] = {}
    for row in rows:
        info = kit_info(row)
        if info["kit_forced"]:
            continue
        message = info["kit_path_problem"]
        if not message and not folder_kit(row.get("path") or ""):
            folder = os.path.dirname(row.get("path") or "")
            first = first_in_dir.setdefault(folder, row)
            if first is not row:
                a, b = doc_cipher(first.get("doc_code")), doc_cipher(row.get("doc_code"))
                ra, rb = _to_int(first.get("revision")), _to_int(row.get("revision"))
                if cipher_key(a) != cipher_key(b):
                    message = f"шифр {b} ≠ шифр комплекта {a}"
                elif ra != rb:
                    message = f"изм. {rb} ≠ изм. комплекта {ra}"
        if message:
            conflicts.append({"id": row["id"], "path": row.get("path") or "", "message": message})
    return conflicts


def group_kits(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    """Файлы по комплектам (шифр, изм., дата)."""
    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        info = kit_info(row)
        groups[(info["kit_code"], info["kit_revision"], info["kit_date"])].append(row)
    return dict(groups)
