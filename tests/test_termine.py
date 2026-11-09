from datetime import datetime, timezone
from pathlib import Path

from study_agent.pipeline.moodle_api import Deadline
from study_agent.pipeline.termine import load_termine, merge_deadlines, upcoming_termine

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 08:00 in Zürich
GENAI = "Generative KI & Agentensysteme 26H2"
DL = "26HS Deep Learning BAI"

GOOD = f"""kurs: "{GENAI}"
kurs_id: 70299
termine:
  - datum: 2026-10-12
    titel: Erste lauffähige Version, Tracing funktioniert
    art: meilenstein
    quelle: GenAI Agents Semesterprogramm_neu.pdf, Folie 1
  - datum: 2026-11-23
    zeit: "13:00"
    titel: Abschlusspräsentation
    art: praesentation
    quelle: GenAI Agents Semesterprogramm_neu.pdf, Folie 1
"""


def write(dir_: Path, name: str, text: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / name).write_text(text)


def local(course, due, kind, name="T", course_id=0):
    return Deadline(course, name, due, "", kind, False, "quelle.pdf", True, course_id)


def test_load_all_day_and_timed_in_zurich_time(tmp_path):
    write(tmp_path, "genai.yaml", GOOD)
    events, errors = load_termine(tmp_path)
    assert errors == []
    first, second = events
    assert (first.course, first.course_id, first.kind, first.all_day) == (GENAI, 70299, "meilenstein", True)
    assert first.due == datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc)  # 23:59 CEST
    assert first.source == "GenAI Agents Semesterprogramm_neu.pdf, Folie 1"
    assert not second.all_day
    assert second.due == datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)  # 13:00 CET


def test_unquoted_time_and_missing_source(tmp_path):
    write(tmp_path, "k.yaml", "kurs: K\ntermine:\n  - datum: 2026-11-23\n    zeit: 13:00\n    titel: P\n")
    [event], errors = load_termine(tmp_path)
    assert errors == []
    assert event.due == datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    assert (event.source, event.kind, event.course_id) == ("k.yaml", "termin", 0)


def test_bad_files_and_entries_are_reported_not_fatal(tmp_path):
    write(tmp_path, "genai.yaml", GOOD)
    write(tmp_path, "kaputt.yaml", "kurs: [unclosed\n")
    write(tmp_path, "mix.yaml", "kurs: K\ntermine:\n"
          "  - {datum: 14.9, titel: Alt}\n"
          "  - {datum: 2026-10-20, titel: Gut}\n"
          "  - {datum: 2026-10-21, titel: X, art: party}\n")
    events, errors = load_termine(tmp_path)
    assert {e.name for e in events} == {"Erste lauffähige Version, Tracing funktioniert", "Abschlusspräsentation", "Gut"}
    assert len(errors) == 3
    assert any(e.startswith("kaputt.yaml:") for e in errors)
    assert any(e.startswith("mix.yaml Eintrag 1:") and "datum" in e for e in errors)
    assert any(e.startswith("mix.yaml Eintrag 3:") and "party" in e for e in errors)
    assert load_termine(tmp_path / "fehlt") == ([], [])


def test_upcoming_keeps_today_drops_past_and_far_future(tmp_path):
    write(tmp_path, "k.yaml", "kurs: K\ntermine:\n"
          "  - {datum: 2027-01-20, titel: Später}\n"
          "  - {datum: 2026-10-20, titel: Bald}\n"
          "  - {datum: 2026-10-06, titel: Gestern}\n"
          "  - {datum: 2026-10-07, titel: Heute}\n")
    events, _ = load_termine(tmp_path)
    assert [e.name for e in upcoming_termine(events, NOW, days=14)] == ["Heute", "Bald"]


def test_merge_drops_only_duplicate_submissions():
    due = datetime(2026, 12, 18, 22, 59, tzinfo=timezone.utc)  # 23:59 CET
    moodle = [Deadline(DL, "Upload Projekt", due, "https://m/e/1", "assign", False, course_id=69210)]
    merged = merge_deadlines(moodle, [
        local(DL, due, "abgabe", "Projektabgabe", course_id=69210),
        local(DL, due, "praesenz", "Präsenzpflicht", course_id=69210),
        local(GENAI, datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc), "meilenstein", "Erste Version"),
    ])
    assert [d.name for d in merged] == ["Erste Version", "Upload Projekt", "Präsenzpflicht"]


def test_merge_by_course_id_even_if_names_differ():
    due = datetime(2026, 10, 29, 22, 59, tzinfo=timezone.utc)
    moodle = [Deadline("Praxisprojekt (Moodle-Name)", "Retro", due, "u", "assign", False, course_id=70658)]
    assert merge_deadlines(moodle, [local("Ordnername ganz anders", due, "abgabe", course_id=70658)]) == moodle


def test_merge_falls_back_to_normalised_names():
    due = datetime(2026, 10, 29, 22, 59, tzinfo=timezone.utc)
    moodle = [Deadline("3-26HS.W-B-BAI-000405.EN/VZTZ Praxisprojekt", "Retro", due, "u", "assign", False)]
    assert merge_deadlines(moodle, [local("3-26HS.W-B-BAI-000405.EN⧸VZTZ Praxisprojekt", due, "abgabe")]) == moodle
