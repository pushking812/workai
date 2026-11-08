from core import config


def test_defaults_when_missing(tmp_path):
    data = config.load_config(str(tmp_path / "nope.json"))
    assert data == config.DEFAULTS


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "sub" / "config.json")
    config.save_config(
        {"directories": ["C:/a", "C:/b", "C:/a"], "background_mode": False, "interval_minutes": 15}, path
    )
    data = config.load_config(path)
    assert data["directories"] == ["C:/a", "C:/b"]
    assert data["background_mode"] is False
    assert data["interval_minutes"] == 15


def test_bad_values_and_broken_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    assert config.load_config(str(path)) == config.DEFAULTS
    saved = config.save_config({"interval_minutes": 0, "directories": "x"}, str(path))
    assert saved["interval_minutes"] == 1
    assert saved["directories"] == []


def test_ui_state_saved_and_partial_updates_keep_it(tmp_path):
    path = str(tmp_path / "config.json")
    ui = {"tree_mode": "section-type", "sort": {"key": "path", "dir": -1}, "filter": "апс", "expanded": ["a|b"]}
    config.save_config({"ui": ui}, path)
    config.save_config({"directories": ["C:/a"]}, path)
    data = config.load_config(path)
    assert data["ui"] == ui
    assert data["directories"] == ["C:/a"]
    config.save_config({"ui": {"tree_mode": "bad", "sort": {"key": 1}}}, path)
    assert config.load_config(path)["ui"] == {}
