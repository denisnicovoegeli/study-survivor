import json
from pathlib import Path

from study_agent.config import load_moodle_config, load_settings


def write_cfg(tmp_path: Path, **raw) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(raw))
    return p


def test_urls_with_root_path(tmp_path):
    cfg = load_moodle_config(write_cfg(tmp_path, token="SECRET", moodle_domain="moodle.fhnw.ch", moodle_path="/"))
    assert cfg.site_url == "https://moodle.fhnw.ch"
    assert cfg.base_url == "https://moodle.fhnw.ch/webservice/rest/server.php"


def test_urls_normalise_missing_slashes(tmp_path):
    cfg = load_moodle_config(write_cfg(tmp_path, token="SECRET", moodle_domain="m.example.org", moodle_path="moodle"))
    assert cfg.site_url == "https://m.example.org/moodle"
    assert cfg.base_url == "https://m.example.org/moodle/webservice/rest/server.php"


def test_token_not_in_repr(tmp_path):
    cfg = load_moodle_config(write_cfg(tmp_path, token="SECRET", moodle_domain="x", moodle_path="/"))
    assert "SECRET" not in repr(cfg)
    assert cfg.token == "SECRET"


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDY_PROJECT_DIR", str(tmp_path / "proj"))
    s = load_settings()
    assert s.moodle_db == tmp_path / "data" / "moodle_state.db"
    assert s.moodle_config_path == tmp_path / "data" / "config.json"
    proj = tmp_path / "proj"
    assert (s.knowledge_dir, s.lernen_dir, s.briefings_dir) == (proj / "knowledge", proj / "lernen", proj / "briefings")
    assert (s.state_dir, s.termine_dir, s.klassen_path) == (proj / "state", proj / "termine", proj / "klassen.yaml")
