"""Конвертация старых `.doc` в `.docx` через установленный Microsoft Word.

Штамп читается только из OOXML, поэтому бинарный формат Word 97-2003
сначала нужно привести к `.docx`. Используется COM-автоматизация Word
(`pywin32`); если Word недоступен, вызывающий код получает `None` и
обрабатывает файл как неподдерживаемый.
"""

from __future__ import annotations

import hashlib
import os

WD_FORMAT_DOCX = 16


def is_doc_file(file_path: str) -> bool:
    """Файл в старом бинарном формате Word (`.doc`)."""
    return os.path.splitext(file_path)[1].lower() == ".doc"


def convert_doc_to_docx(source_path: str, target_path: str) -> str | None:
    """Сохраняет копию `.doc` как `.docx`. Возвращает путь или None при сбое."""
    try:
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return None

    source = os.path.abspath(source_path)
    target = os.path.abspath(target_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)

    try:
        import pythoncom  # noqa: PLC0415
    except ImportError:
        pythoncom = None

    # COM в фоновом потоке нужно инициализировать явно (иначе DispatchEx падает).
    if pythoncom is not None:
        pythoncom.CoInitialize()
    try:
        return _convert_with_word(win32com.client, source, target)
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def _convert_with_word(client, source: str, target: str) -> str | None:
    word = None
    try:
        word = client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(source, ReadOnly=True, AddToRecentFiles=False)
        document.SaveAs2(target, FileFormat=WD_FORMAT_DOCX)
        document.Close(False)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
    return target if os.path.exists(target) else None


def read_doc_stamp_source(file_path: str, cache_dir: str) -> str:
    """Путь к `.docx` для разбора штампа: сам файл или его конвертация.

    Конвертация кэшируется по имени файла, чтобы повторный прогон папки
    не открывал Word для каждого документа.
    """
    if not is_doc_file(file_path):
        return file_path
    # Ключ кэша включает путь, размер и mtime: в папках ИЗМ0/ИЗМ1 файлы
    # называются одинаково, а содержимое (штамп) разное.
    stat = os.stat(file_path)
    key = "|".join((os.path.abspath(file_path).lower(), str(stat.st_size), str(int(stat.st_mtime))))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    name = os.path.splitext(os.path.basename(file_path))[0] + "_" + digest + ".docx"
    target = os.path.join(cache_dir, name)
    if os.path.exists(target):
        return target
    converted = convert_doc_to_docx(file_path, target)
    return converted or file_path
