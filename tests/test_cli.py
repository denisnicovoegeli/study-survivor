import json
from datetime import datetime, timezone

import pytest
from helpers import make_db

from study_agent.cli import main

NOW_TS = int(datetime.now(timezone.utc).timestamp())


@pytest.fixture
def env(tmp_path, monkeypatch):
    data, proj = tmp_path / "data", tmp_path / "proj"
    data.mkdir()
    (data / "config.json").write_text(json.dumps({"token": "SECRET", "moodle_domain": "moodle.test", "moodle_path": "/"}))
    rel = "DL/Woche 3/W03.pdf"
    make_db(data / "moodle_state.db", [dict(course_id=69210, course_fullname="26HS Deep Learning BAI",
                                            content_filename="W03.pdf", saved_to=str(data / rel),
                                            content_timemodified=NOW_TS, module_id=77)])
    (proj / "knowledge" / "DL" / "Woche 3").mkdir(parents=True)
    (proj / "knowledge" / ".manifest.json").write_text(
        json.dumps({rel: {"sig": [1, 1], "klasse": "folien", "seiten": 2, "visuell": [2]}}))
    monkeypatch.setenv("STUDY_DATA_DIR", str(data))
    monkeypatch.setenv("STUDY_PROJECT_DIR", str(proj))
    return proj, rel


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_pending_json_lists_current_file(env, capsys):
    _, rel = env
    code, out, err = run(capsys, "pending", "--json")
    assert code == 0 and "SECRET" not in out + err
    [item] = json.loads(out)
    assert (item["rel"], item["route"], item["visual"]) == (rel, "voll", [2])
    assert item["moodle_link"] == "https://moodle.test/mod/resource/view.php?id=77"


def test_check_folien_then_done(env, capsys):
    proj, rel = env
    assert run(capsys, "check-folien", rel)[:2] == (1, "fehlende Folien: [1, 2]\n")
    assert run(capsys, "done", rel)[0] == 1
    (proj / "knowledge" / f"{rel}.folien.md").write_text("## Folie 1 · A\nx\n\n## Folie 2 · B\ny\n")
    assert run(capsys, "check-folien", rel)[:2] == (0, "vollständig: 2 Folien\n")
    assert run(capsys, "done", rel)[0] == 0
    assert json.loads(run(capsys, "pending", "--json")[1]) == []


def test_klasse_sets_override_and_rejects_unknown(env, capsys):
    proj, rel = env
    assert run(capsys, "klasse", rel, "ueberspringen")[0] == 0
    assert "ueberspringen" in (proj / "klassen.yaml").read_text()
    assert json.loads(run(capsys, "pending", "--json")[1]) == []
    code, _, err = run(capsys, "klasse", rel, "party")
    assert code == 1 and "unbekannt" in err


def test_termine_exit_code_reflects_yaml_errors(env, capsys):
    proj, _ = env
    (proj / "termine").mkdir()
    assert run(capsys, "termine")[0] == 0
    (proj / "termine" / "x.yaml").write_text("kurs: X\ntermine:\n  - {datum: 14.9, titel: Alt}\n")
    code, _, err = run(capsys, "termine")
    assert code == 1 and "x.yaml Eintrag 1" in err


def test_courses_current(env, capsys):
    code, out, _ = run(capsys, "courses", "--current")
    assert code == 0 and "69210" in out and "26HS Deep Learning BAI" in out


def test_schema_change_gives_clear_error(env, capsys, tmp_path):
    (tmp_path / "data" / "moodle_state.db").unlink()
    make_db(tmp_path / "data" / "moodle_state.db", [], schema="CREATE TABLE files (file_id INTEGER PRIMARY KEY)")
    code, _, err = run(capsys, "pending")
    assert code == 2 and "Spalten fehlen" in err


def test_briefing_print_outputs_markdown_without_notify(env, capsys, monkeypatch):
    import study_agent.cli as cli

    class Client:
        def upcoming_deadlines(self, days, now=None):
            return []

    calls = []
    monkeypatch.setattr(cli, "_client", lambda settings: Client())
    monkeypatch.setattr(cli, "notify", lambda *a: calls.append(a))
    code, out, err = run(capsys, "briefing", "--print")
    proj, _ = env
    [path] = (proj / "briefings").glob("*.md")
    assert code == 0 and out == path.read_text() and out.startswith("#")
    assert calls == [] and "SECRET" not in out + err


def test_eigene_upload_stores_file(env, capsys):
    proj, _ = env
    data = proj.parent / "data"
    pdf = data / "test.pdf"
    pdf.write_bytes(b"%PDF test")
    code, out, _ = run(capsys, "eigene-upload", "--course", "Reinforcement Learning", str(pdf), "--json")
    assert code == 0
    result = json.loads(out)
    assert (result["course"], result["name"]) == ("Reinforcement Learning", "test.pdf")
    assert result["rel"] == "_eigene/Reinforcement Learning/test.pdf"
    assert (data / "_eigene" / "Reinforcement Learning" / "test.pdf").read_bytes() == b"%PDF test"


def test_eigene_upload_rejects_bad_extension(env, capsys):
    proj, _ = env
    data = proj.parent / "data"
    f = data / "x.txt"
    f.write_bytes(b"x")
    code, _, err = run(capsys, "eigene-upload", "--course", "Kurs", str(f))
    assert code == 1 and "nur" in err
