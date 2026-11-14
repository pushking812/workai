"""Автообновление книг Power Query в собственном скрытом Excel (`scripts/refresh_books.ps1`)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "refresh_books.ps1")


def refresh_books(paths: list[str], timeout_sec: int = 900) -> dict[str, Any]:
    """Обновляет и сохраняет книги по порядку. `status`: ok, busy (открыт Excel пользователя), error, unavailable."""
    if sys.platform != "win32" or not os.path.isfile(SCRIPT):
        return {"status": "unavailable", "log": ""}
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SCRIPT,
             "-Books", "|".join(os.path.abspath(p) for p in paths), "-TimeoutSec", str(timeout_sec)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_sec + 60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "log": str(exc)}
    log = (proc.stdout or "").strip()
    status = {0: "ok", 2: "busy"}.get(proc.returncode, "error")
    return {"status": status, "log": log or (proc.stderr or "").strip(), "issues": parse_issues(log)}


RECONCILE_SCRIPT = os.path.join(os.path.dirname(SCRIPT), "make_reconcile.py")


def make_reconcile_report(folder: str, timeout_sec: int = 170) -> dict[str, Any]:
    """Отчёт сверки итогов последнего комплекта в `folder` (`scripts/make_reconcile.py`).

    `status`: ok (+`path`, `log`) или error (+`message`)."""
    if not os.path.isfile(RECONCILE_SCRIPT):
        return {"status": "error", "message": "Не найден scripts/make_reconcile.py"}
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", RECONCILE_SCRIPT, os.path.abspath(folder)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_sec, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "message": str(exc)}
    out = (proc.stdout or "").strip()
    path = next((line[6:].strip() for line in out.splitlines() if line.startswith("saved ")), "")
    if proc.returncode or not path:
        return {"status": "error", "message": (proc.stderr or out or "Отчёт не создан").strip()[-1500:]}
    warnings = [line for line in out.splitlines() if line.startswith(("ВНИМАНИЕ", "НЕТ в"))]
    return {"status": "ok", "path": path, "warnings": warnings}


def parse_issues(log: str) -> dict[str, int]:
    """Счётчики листа «Ошибки» из строки `ISSUES <книга>: тип=число;тип=число` (тип проблемы -> число строк)."""
    issues: dict[str, int] = {}
    for line in log.splitlines():
        if not line.startswith("ISSUES "):
            continue
        for part in line.split(": ", 1)[-1].split(";"):
            kind, _, count = part.rpartition("=")
            if kind.strip() and count.strip().isdigit():
                issues[kind.strip()] = issues.get(kind.strip(), 0) + int(count)
    return issues
