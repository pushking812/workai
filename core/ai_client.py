"""Прямой запрос к AI-модели (Ask API, `POST /v1/ask`, ответ потоком SSE).

Используется только если включено «Использовать AI» в настройках и есть ключ:
сначала переменная окружения ASK_API_KEY, затем `ai_api_key` из data/config.json.
Только стандартная библиотека. Документы уходят на внешний сервер: включать осознанно.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://ask.oryxml.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_PDF_B64 = 10_000_000  # лимит API на PDF (символов base64)


class AIError(RuntimeError):
    """Ошибка обращения к модели (сеть, лимит, неверный ключ, пустой ответ)."""

    def __init__(self, message: str, code: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def get_key(settings: dict[str, Any] | None = None) -> str:
    return (os.environ.get("ASK_API_KEY") or (settings or {}).get("ai_api_key") or "").strip()


def is_enabled(settings: dict[str, Any] | None) -> bool:
    """AI включён флажком и ключ задан."""
    return bool(settings and settings.get("use_ai") and get_key(settings))


def file_part(path: str | Path) -> dict[str, Any]:
    """Файл для поля `files`: картинка или PDF (base64), текст — как текст."""
    p = Path(path)
    mt = mimetypes.guess_type(p.name)[0] or ""
    raw = p.read_bytes()
    if mt.startswith("image/") or mt == "application/pdf":
        data = base64.b64encode(raw).decode("ascii")
        if mt == "application/pdf" and len(data) > MAX_PDF_B64:
            raise AIError(f"PDF слишком большой для API: {p.name}", "file_too_large")
        # вид файла для PDF в документации не назван; проверено: принимается kind="pdf"
        kind = "image" if mt.startswith("image/") else "pdf"
        return {"kind": kind, "name": p.name, "mediaType": mt, "data": data}
    return {"kind": "text", "name": p.name, "text": raw.decode("utf-8", "replace")}


def parse_sse(lines) -> tuple[str, dict[str, Any]]:
    """Разбирает строки SSE: возвращает (текст из delta, данные done). error -> AIError."""
    event, text, done, finished = "", [], {}, False
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except ValueError:
                continue
            if event == "delta":
                text.append(data.get("text", ""))
            elif event == "error":
                raise AIError(data.get("message", "ошибка модели"), data.get("code", ""),
                              None)
            elif event == "done":
                done, finished = data, True
    if not finished:
        raise AIError("соединение оборвалось до конца ответа", "dropped")
    return "".join(text), done


def ask(prompt: str, *, settings: dict[str, Any] | None = None, system: str = "",
        files: list[dict[str, Any]] | None = None, model: str = "", timeout: float = 240.0,
        retries: int = 2, opener=urllib.request.urlopen) -> str:
    """Один вопрос к модели, возвращает текст ответа целиком."""
    key = get_key(settings)
    if not key:
        raise AIError("не задан ASK_API_KEY", "no_key")
    body: dict[str, Any] = {"prompt": prompt, "model": model or (settings or {}).get("ai_model") or DEFAULT_MODEL}
    if system:
        body["system"] = system
    if files:
        body["files"] = files
    payload = json.dumps(body).encode("utf-8")
    last: AIError | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            BASE_URL + "/v1/ask", data=payload, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Idempotency-Key": f"workai-{time.time_ns()}-{attempt}"})
        try:
            with opener(req, timeout=timeout) as resp:
                text, _ = parse_sse(resp)
                return text
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8")).get("error", {})
            except Exception:
                err = {}
            wait = e.headers.get("Retry-After") if e.headers else None
            last = AIError(err.get("message") or f"HTTP {e.code}", err.get("code", str(e.code)),
                           float(wait) if wait and wait.isdigit() else None)
            if e.code not in (429, 502, 503, 504) or attempt == retries:
                raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = AIError(f"нет связи с сервером: {e}", "network")
            if attempt == retries:
                raise last
        time.sleep(min(last.retry_after or 5.0, 30.0) if last else 5.0)
    raise last or AIError("неизвестная ошибка")


def strip_fences(text: str) -> str:
    """Убирает ```-обёртку, если модель всё же её добавила."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()

