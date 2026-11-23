import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from helpers import make_db

from study_agent.pipeline.briefing import notify, render_briefing, run_briefing, summary_line
from study_agent.config import Settings
from study_agent.pipeline.moodle_api import Deadline, MoodleError
from study_agent.pipeline.moodle_db import FileRecord, read_last_file_id, write_last_file_id
from study_agent.pipeline.pending import PendingFile

NOW = datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc)  # Montag, 08:30 in Zürich
SITE = "https://moodle.test"
SEP = int(datetime(2026, 9, 28, tzinfo=timezone.utc).timestamp())


def dl(name, delta, overdue=False):
    return Deadline("26HS Deep Learning BAI", name, NOW + delta, "https://m/e", "assign", overdue)


def rec(course, name, updated=False):
    return FileRecord(1, 1, course, 1, "Woche 3", 42, "resource", name, name, Path(f"/x/{name}"), "",
                      datetime(2026, 10, 2, 10, tzinfo=timezone.utc), updated)


def pend(name, route="voll", klasse="folien", pages=57, reason="neu"):
    return PendingFile(f"K/S/{name}", "26HS Deep Learning BAI", 69210, "S", name, klasse, route, reason, pages, [],
                       Path("/s"), Path("/r"), Path("/f"), Path("/l"), Path("/c"), "")


def test_render_groups_overdue_and_upcoming_in_zurich_time():
    md = render_briefing(date(2026, 10, 5), [dl("Alt", -timedelta(days=1), overdue=True),
                                             dl("Projekt", timedelta(days=2, hours=15, minutes=29))],
                         [rec("Marketing-Modul BAI 2026", "Folien.pdf")], NOW, site_url=SITE)
    assert md.startswith("# Briefing Montag, 05.10.2026")
    over, rest = md.split("## Fällig")
    assert "Alt" in over and "## Überfällig" in over
    assert "**Mi 07.10. 23:59**" in rest  # 21:59 UTC = 23:59 CEST
    assert "### Marketing-Modul BAI 2026" in md
    assert f"- Woche 3 / Folien.pdf · 02.10. · [Moodle]({SITE}/mod/resource/view.php?id=42)" in md


def test_render_empty_sections_and_error():
    md = render_briefing(date(2026, 10, 5), None, [], NOW, error="invalidtoken")
    assert "Moodle-API nicht erreichbar: invalidtoken" in md
    assert md.count("_Keine._") == 1  # nur neue Dateien; Deadlines-Bereich zeigt den Fehler


def test_render_baseline_note():
    assert "Erster Lauf" in render_briefing(date(2026, 10, 5), [], [], NOW, baseline=True)


def test_render_local_termin_without_time_and_with_source():
    t = Deadline("Generative KI & Agentensysteme 26H2", "Erste lauffähige Version",
                 datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc), "", "meilenstein", False,
                 "GenAI Agents Semesterprogramm_neu.pdf, Folie 1", True)
    md = render_briefing(date(2026, 10, 5), [t], [], NOW)
    assert ("- **Mo 12.10.** · Generative KI & Agentensysteme 26H2 — Erste lauffähige Version"
            " _(meilenstein · GenAI Agents Semesterprogramm_neu.pdf, Folie 1)_") in md


def test_render_pending_errors_and_missing_termine():
    pending = [pend("W03_training.pdf"), pend("Programm.pdf", "info", "semesterprogramm", 2, "veraltet"),
               *(pend(f"f{i}.pdf") for i in range(10))]
    md = render_briefing(date(2026, 10, 5), [], [], NOW, pending=pending, config_errors=["x.yaml: kaputt"],
                         no_termine=True)
    assert "## Zu verarbeiten\n12 Dateien (11 Folien, 1 Semesterprogramm/Projekt, 0 unklar)" in md
    assert "- 26HS Deep Learning BAI / W03_training.pdf (folien, 57 S.)" in md
    assert "- 26HS Deep Learning BAI / Programm.pdf (semesterprogramm, 2 S., veraltet)" in md
    assert "- … und 2 weitere" in md
    assert "- ⚠️ x.yaml: kaputt" in md
    assert "Noch keine Termine aus Semesterprogrammen erfasst" in md


def test_summary_line_counts_urgent_and_pending():
    s = summary_line([dl("A", timedelta(days=1)), dl("B", timedelta(days=10))], [rec("K", "a"), rec("K", "b")], NOW,
                     None, pending_count=3)
    assert s == "1 Deadline in ≤3 Tagen · 2 neue Dateien · 3 zu verarbeiten"
    assert summary_line(None, [], NOW, "invalidtoken") == "⚠️ Moodle-API: invalidtoken · 0 neue Dateien"


class FakeClient:
    def __init__(self, deadlines=None, error=None):
        self.deadlines, self.error = deadlines or [], error

    def upcoming_deadlines(self, days, now=None):
        if self.error:
            raise MoodleError("x", self.error)
        return self.deadlines


def settings_with_db(tmp_path, n_files, **row):
    data = tmp_path / "data"
    make_db(data / "moodle_state.db", [dict(course_id=69210, course_fullname="26HS Deep Learning BAI",
                                            content_filename=f"f{i}.pdf", content_timemodified=SEP,
                                            saved_to=str(data / "DL" / "Woche 1" / f"f{i}.pdf"), **row)
                                       for i in range(n_files)])
    return Settings(data_dir=data, project_dir=tmp_path / "proj")


def test_first_run_sets_baseline_without_listing_all_files(tmp_path):
    s = settings_with_db(tmp_path, 777)
    path, summary = run_briefing(s, FakeClient(), SITE, now=NOW)
    text = path.read_text()
    assert path == s.briefings_dir / "2026-10-05.md"
    assert "Erster Lauf" in text and "f1.pdf" not in text
    assert read_last_file_id(s.state_dir) == 777
    assert summary.endswith("0 neue Dateien")


def test_second_run_lists_new_files_and_advances_watermark(tmp_path):
    s = settings_with_db(tmp_path, 5)
    write_last_file_id(s.state_dir, 3)
    path, summary = run_briefing(s, FakeClient(), SITE, now=NOW)
    assert "f3.pdf" in path.read_text() and "f4.pdf" in path.read_text()
    assert read_last_file_id(s.state_dir) == 5
    assert summary.endswith("2 neue Dateien")


def test_moodle_error_still_writes_briefing_with_termine(tmp_path):
    s = settings_with_db(tmp_path, 1)
    write_last_file_id(s.state_dir, 1)
    s.termine_dir.mkdir(parents=True)
    (s.termine_dir / "dl.yaml").write_text(
        "kurs: 26HS Deep Learning BAI\ntermine:\n  - {datum: 2026-10-08, titel: Zwischenstand, art: meilenstein}\n")
    path, summary = run_briefing(s, FakeClient(error="invalidtoken"), SITE, now=NOW)
    text = path.read_text()
    assert "Moodle-API nicht erreichbar: invalidtoken" in text
    assert "Zwischenstand" in text and "dl.yaml" in text
    assert "Noch keine Termine" not in text
    assert "invalidtoken" in summary


def test_run_lists_pending_files_of_current_semester(tmp_path):
    s = settings_with_db(tmp_path, 2)
    write_last_file_id(s.state_dir, 2)
    manifest = {f"DL/Woche 1/f{i}.pdf": {"sig": [1, 1], "klasse": "folien", "seiten": 3, "visuell": []} for i in range(2)}
    s.knowledge_dir.mkdir(parents=True)
    (s.knowledge_dir / ".manifest.json").write_text(json.dumps(manifest))
    path, summary = run_briefing(s, FakeClient(), SITE, now=NOW)
    assert "## Zu verarbeiten\n2 Dateien (2 Folien" in path.read_text()
    assert summary.endswith("2 zu verarbeiten")


def test_run_lists_eigene_dateien_als_neu_mit_quelle_eigene(tmp_path):
    from study_agent.pipeline.eigene import advance_eigene_state

    s = settings_with_db(tmp_path, 1)
    write_last_file_id(s.state_dir, 1)  # keine neuen Moodle-Dateien
    known = s.data_dir / "_eigene" / "Marketing" / "a.pdf"
    known.parent.mkdir(parents=True)
    known.write_bytes(b"x")
    advance_eigene_state(s.data_dir, s.state_dir)  # Basislinie: a.pdf bekannt
    (s.data_dir / "_eigene" / "Marketing" / "b.pdf").write_bytes(b"x")  # neu

    path, summary = run_briefing(s, FakeClient(), SITE, now=NOW)
    text = path.read_text()
    assert "b.pdf" in text and "eigene" in text
    assert "a.pdf" not in text  # schon bekannt, kein „neues“ File
    assert summary.endswith("1 neue Dateien")


def test_notify_is_noop_without_osascript(monkeypatch):
    import subprocess as sp

    calls = []
    monkeypatch.setattr("study_agent.pipeline.briefing.shutil.which", lambda _cmd: None)
    monkeypatch.setattr(sp, "run", lambda *a, **k: calls.append(a))
    notify("Titel", "Meldung")
    assert calls == []


def test_notify_runs_osascript_when_available(monkeypatch):
    import subprocess as sp

    calls = []
    monkeypatch.setattr("study_agent.pipeline.briefing.shutil.which", lambda _cmd: "/usr/bin/osascript")
    monkeypatch.setattr(sp, "run", lambda *a, **k: calls.append(a))
    notify("Titel", "Meldung")
    assert calls and "osascript" in calls[0][0]


def test_create_briefing_suggestions_creates_and_deduplicates(tmp_path):
    from study_agent.pipeline.briefing import create_briefing_suggestions
    from study_agent.config import Settings
    from study_agent.pipeline.pending import PendingFile

    s = Settings(data_dir=tmp_path / "data", project_dir=tmp_path / "proj")
    s.state_dir.mkdir(parents=True)

    pf1 = PendingFile(
        rel="Kurs/Woche 07/w7.pdf", course="Deep Learning", course_id=1, section="Woche 07",
        name="w7.pdf", klasse="folien", route="voll", reason="neu", pages=10, visual=[],
        source=tmp_path / "data/Kurs/Woche 07/w7.pdf", raw_md=tmp_path / "raw.md",
        folien_md=tmp_path / "folien.md", lernen_dir=tmp_path / "lernen",
        course_lernen_dir=tmp_path / "lernen/Kurs", moodle_link=""
    )
    pf2 = PendingFile(
        rel="Kurs/Woche 07/w7_uebung.pdf", course="Deep Learning", course_id=1, section="Woche 07",
        name="w7_uebung.pdf", klasse="folien", route="voll", reason="neu", pages=5, visual=[],
        source=tmp_path / "data/Kurs/Woche 07/w7_uebung.pdf", raw_md=tmp_path / "raw.md",
        folien_md=tmp_path / "folien.md", lernen_dir=tmp_path / "lernen",
        course_lernen_dir=tmp_path / "lernen/Kurs", moodle_link=""
    )

    added = create_briefing_suggestions(s, [pf1, pf2])
    assert len(added) == 1
    card = added[0]
    assert card["title"] == "W07 verarbeiten"
    assert card["column"] == "vorschlaege"
    assert card["skill"] == "verarbeiten"
    assert card["args"] == ["Deep Learning", "Woche 07"]

    # Zweiter Aufruf ohne neue Dateien erzeugt keine Duplikate
    added2 = create_briefing_suggestions(s, [pf1, pf2])
    assert added2 == []
