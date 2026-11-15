"""AI-клиент, разбор сырого CSV от модели, настройки AI. Сеть не используется."""
import io
import json
import urllib.error

import pytest

from core import ai_client, config, rooms_ai


def _sse(*events):
    out = []
    for name, data in events:
        out.append(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
    return io.BytesIO("".join(out).encode("utf-8"))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_parse_sse_collects_deltas():
    text, done = ai_client.parse_sse(_sse(("status", {"state": "writing"}), ("delta", {"text": "При"}),
                                          ("delta", {"text": "вет"}), ("done", {"messageId": "1"})))
    assert text == "Привет" and done["messageId"] == "1"


def test_parse_sse_error_and_dropped():
    with pytest.raises(ai_client.AIError) as e:
        ai_client.parse_sse(_sse(("error", {"message": "лимит", "code": "subscription_limit"})))
    assert e.value.code == "subscription_limit"
    with pytest.raises(ai_client.AIError):
        ai_client.parse_sse(_sse(("delta", {"text": "x"})))


def test_ask_sends_key_system_and_files(monkeypatch):
    monkeypatch.delenv("ASK_API_KEY", raising=False)
    seen = {}

    def opener(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(_sse(("delta", {"text": "ok"}), ("done", {})).getvalue())

    out = ai_client.ask("q", settings={"ai_api_key": "sk-ask-1"}, system="s",
                        files=[{"kind": "text", "name": "a", "text": "t"}], opener=opener)
    assert out == "ok"
    assert seen["auth"] == "Bearer sk-ask-1"
    assert seen["body"]["system"] == "s" and seen["body"]["files"][0]["name"] == "a"
    assert seen["body"]["model"] == ai_client.DEFAULT_MODEL


def test_ask_without_key_fails(monkeypatch):
    monkeypatch.delenv("ASK_API_KEY", raising=False)
    with pytest.raises(ai_client.AIError) as e:
        ai_client.ask("q", settings={})
    assert e.value.code == "no_key"


def test_ask_http_error_not_retried_for_400(monkeypatch):
    monkeypatch.setenv("ASK_API_KEY", "k")
    calls = []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(
            json.dumps({"error": {"code": "invalid_body", "message": "плохо"}}).encode()))

    with pytest.raises(ai_client.AIError) as e:
        ai_client.ask("q", opener=opener)
    assert e.value.code == "invalid_body" and len(calls) == 1


def test_is_enabled_needs_flag_and_key(monkeypatch):
    monkeypatch.delenv("ASK_API_KEY", raising=False)
    assert not ai_client.is_enabled({"use_ai": True})
    assert not ai_client.is_enabled({"use_ai": False, "ai_api_key": "k"})
    assert ai_client.is_enabled({"use_ai": True, "ai_api_key": "k"})
    monkeypatch.setenv("ASK_API_KEY", "env")
    assert ai_client.get_key({"ai_api_key": "cfg"}) == "env"


def test_file_part_pdf_and_text(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4 x")
    part = ai_client.file_part(p)
    assert part["kind"] == "pdf" and part["mediaType"] == "application/pdf" and part["data"]
    t = tmp_path / "a.txt"
    t.write_text("текст", encoding="utf-8")
    assert ai_client.file_part(t) == {"kind": "text", "name": "a.txt", "text": "текст"}


# ----------------------------------------------------------------- rooms_ai
CSV = ('"NN по правоустанавливающим документам","NN внутр.","Назначение помещений","Площадь помещений по ПБ, кв.м",'
       '"Площадь помещений по факту, кв.м","Подразделение использующ. помещение","Примечание"\n'
       '"ТРЕТИЙ ЭТАЖ","","","","","",""\n'
       '"12-Н (ч.п.5)","350","Санузел","3,0","3,0","Упр","Ук. 853/Н"\n')


def test_parse_csv_text_plain_and_fenced():
    rows = rooms_ai.parse_csv_text(CSV)
    assert len(rows) == 2 and rows[1][1] == "350" and rows[1][3] == "3,0"
    assert rooms_ai.parse_csv_text("```csv\n" + CSV + "```") == rows


def test_parse_csv_text_model_refusal():
    with pytest.raises(ai_client.AIError) as e:
        rooms_ai.parse_csv_text("ERROR: файл не читается")
    assert e.value.code == "model_refused" and "не читается" in str(e.value)
    with pytest.raises(ai_client.AIError):
        rooms_ai.parse_csv_text("Извините, не могу")


def test_ocr_with_ai_uses_injected_ask(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    got = {}

    def fake(prompt, **kw):
        got.update(kw)
        return CSV

    rows = rooms_ai.ocr_with_ai(pdf, {}, ask=fake)
    assert rows[1][1] == "350" and got["files"][0]["kind"] == "pdf" and "CSV" in got["system"]


# ------------------------------------------------------------------- config
def test_config_ai_defaults_and_hidden_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ASK_API_KEY", raising=False)
    path = str(tmp_path / "c.json")
    assert config.load_config(path)["use_ai"] is False
    saved = config.save_config({"use_ai": True, "ai_api_key": " sk-ask-9 "}, path)
    assert saved["use_ai"] is True and saved["ai_api_key"] == "sk-ask-9"
    pub = config.public_view(saved)
    assert "ai_api_key" not in pub and pub["ai_key_set"] is True and pub["ai_key_from_env"] is False
    # частичное сохранение другого ключа не стирает ключ AI
    config.save_config({"interval_minutes": 5}, path)
    assert config.load_config(path)["ai_api_key"] == "sk-ask-9"
