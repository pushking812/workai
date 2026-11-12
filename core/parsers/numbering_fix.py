"""Автонумерация Word → обычный текст на временной копии.

`docx2python` сам считает номера списков и ошибается (сбрасывает счётчик,
подставляет `)`), поэтому перед разбором таблиц документ прогоняется через
`scripts/docx_fix_numbering.process_file`. Исходный файл не меняется.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterator

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fixer():
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from scripts import docx_fix_numbering

    return docx_fix_numbering


@contextmanager
def numbering_fixed(path: str) -> Iterator[str]:
    """Отдаёт путь к копии с номерами в тексте; при сбое или без списков — исходный путь."""
    if not path.lower().endswith(".docx"):
        yield path
        return
    work_dir = tempfile.mkdtemp(prefix="docx_fixed_")
    try:
        target = os.path.join(work_dir, "fixed.docx")
        try:
            changed = _fixer().process_file(path, target, verbose=False)
        except Exception:  # noqa: BLE001
            changed = None
        yield target if changed and os.path.exists(target) else path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
