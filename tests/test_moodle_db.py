from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from helpers import make_db

from study_agent.pipeline.moodle_db import (MoodleDbError, all_files, clean_text, courses, current_courses, files_since,
                                   max_file_id, read_last_file_id, redact_url, semester_start, write_last_file_id)

SEP_2026 = int(datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp())
JUN_2026 = int(datetime(2026, 6, 12, tzinfo=timezone.utc).timestamp())


def test_files_since_filters_sorts_and_cleans(tmp_path):
    db = make_db(tmp_path / "moodle_state.db", [
        dict(course_fullname="B-Kurs", content_filename="alt.pdf"),
        dict(course_id=70299, course_fullname="B-Kurs", section_id=20, module_id=1234, content_filename="W03.pdf",
             section_name='<span class="course-mod_subsection">1 Generative AI, LLMs &amp; Prompts</span>',
             module_name="Folien Woche 3", saved_to="/x/B/W03.pdf", content_timemodified=SEP_2026),
        dict(course_fullname="A-Kurs ⧸ Gruppe", content_filename="geändert.pdf", old_file_id=1),
        dict(course_fullname="A-Kurs ⧸ Gruppe", content_filename="weg.pdf", deleted=1),
    ])
    files = files_since(db, after_file_id=1)
    assert [(f.course, f.name, f.updated) for f in files] == [("A-Kurs ⧸ Gruppe", "geändert.pdf", True),
                                                              ("B-Kurs", "W03.pdf", False)]
    w03 = files[1]
    assert w03.section == "1 Generative AI, LLMs & Prompts"
    assert (w03.course_id, w03.section_id, w03.module_type, w03.module_name) == (70299, 20, "resource", "Folien Woche 3")
    assert w03.path == Path("/x/B/W03.pdf")
    assert w03.modified == datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert w03.external_url == ""  # pluginfile-URLs brauchen den Token und werden nie herausgegeben
    assert w03.moodle_link("https://moodle.fhnw.ch") == "https://moodle.fhnw.ch/mod/resource/view.php?id=1234"
    assert w03.rel(Path("/x")) == Path("B/W03.pdf")
    assert w03.rel(Path("/anders")) is None


def test_external_links_are_kept_but_secrets_removed(tmp_path):
    db = make_db(tmp_path / "moodle_state.db", [
        dict(module_modname="url", content_filename="Recording", content_fileurl="https://kaggle.com/code/x?tab=1"),
        dict(module_modname="url", content_filename="Voiceflow",
             content_fileurl="https://creator.voiceflow.com/workspace/accept-invite?token=abc123"),
    ])
    by_name = {f.name: f.external_url for f in all_files(db)}
    assert by_name["Recording"] == "https://kaggle.com/code/x?tab=1"
    assert "abc123" not in by_name["Voiceflow"]
    assert by_name["Voiceflow"].startswith("https://creator.voiceflow.com/workspace/accept-invite (Link gekürzt")


def test_clean_text_and_redact_url_helpers():
    assert clean_text("Lernziele &amp; Programm") == "Lernziele & Programm"
    assert clean_text('<span class="x">Folien</span>  ') == "Folien"
    assert redact_url("https://a.ch/p?q=1") == "https://a.ch/p?q=1"
    assert "s3cr3t" not in redact_url("https://a.ch/p?apikey=s3cr3t")


def test_schema_change_is_reported(tmp_path):
    db = make_db(tmp_path / "moodle_state.db", [], schema="CREATE TABLE files (file_id INTEGER PRIMARY KEY, saved_to text)")
    with pytest.raises(MoodleDbError, match="Spalten fehlen: .*course_id"):
        all_files(db)
    with pytest.raises(MoodleDbError):
        all_files(tmp_path / "fehlt.db")


def test_db_opened_read_only(tmp_path):
    db = make_db(tmp_path / "moodle_state.db", [{}])
    before = db.stat().st_mtime_ns
    files_since(db, 0)
    courses(db)
    assert db.stat().st_mtime_ns == before


def test_courses_and_current_semester(tmp_path):
    db = make_db(tmp_path / "moodle_state.db", [
        dict(course_id=70299, course_fullname="Generative KI & Agentensysteme 26H2", content_timemodified=SEP_2026),
        dict(course_id=70299, course_fullname="Generative KI & Agentensysteme 26H2", content_timemodified=JUN_2026),
        dict(course_id=68158, course_fullname="Design Thinking SS2026", content_timemodified=JUN_2026),
    ])
    assert [(c.course_id, c.files) for c in courses(db)] == [(70299, 2), (68158, 1)]
    assert [c.course_id for c in current_courses(db, date(2026, 10, 9))] == [70299]
    assert [c.course_id for c in current_courses(db, date(2026, 6, 20))] == [70299, 68158]


def test_semester_start():
    assert semester_start(date(2026, 10, 9)) == date(2026, 8, 1)
    assert semester_start(date(2027, 1, 15)) == date(2026, 8, 1)
    assert semester_start(date(2027, 3, 1)) == date(2027, 2, 1)


def test_max_file_id_and_watermark(tmp_path):
    assert max_file_id(make_db(tmp_path / "a.db", [])) == 0
    assert max_file_id(make_db(tmp_path / "b.db", [{}, {}, {}])) == 3
    state = tmp_path / "state"
    assert read_last_file_id(state) is None
    write_last_file_id(state, 778)
    assert read_last_file_id(state) == 778
