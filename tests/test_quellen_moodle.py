"""Quellen pro Modul und Moodle-Aktualisierung aus dem Dashboard."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from study_agent.config import Settings
from study_agent.pipeline.quellen import quellen_modul
from study_agent.pipeline.suche import build_index
from study_agent.server.dashboard import routes_moodle
from tests.helpers import make_db

KURS = "Deep Learning"


@pytest.fixture
def settings(tmp_path):
    data, proj = tmp_path / "moodle", tmp_path / "proj"
    kurs = data / KURS / "W1"
    kurs.mkdir(parents=True)
    for name in ("W01.pdf", "scan.pdf", "code.zip"):
        (kurs / name).write_bytes(b"x")
    make_db(data / "moodle_state.db", [
        dict(file_id=1, course_fullname=KURS, section_name="W1", content_filename="W01.pdf",
             saved_to=str(kurs / "W01.pdf")),
        dict(file_id=2, course_fullname=KURS, section_name="W1", content_filename="scan.pdf",
             saved_to=str(kurs / "scan.pdf")),
        dict(file_id=3, course_fullname=KURS, section_name="W1", content_filename="code.zip",
             saved_to=str(kurs / "code.zip")),
        dict(file_id=4, course_fullname=KURS, section_name="W1", module_modname="url", module_name="Notebook",
             content_filename="Notebook.webloc", saved_to=str(kurs / "Notebook.webloc")),
        dict(file_id=5, course_fullname=KURS, section_name="W2", content_filename="weg.pdf",
             saved_to=str(data / KURS / "W2" / "weg.pdf")),
        dict(file_id=6, course_fullname="Anderer Kurs", content_filename="x.pdf", saved_to=str(data / "Anderer Kurs" / "x.pdf")),
    ])
    k = proj / "knowledge" / KURS / "W1"
    k.mkdir(parents=True)
    (k / "W01.pdf.md").write_text("# W01\n\n## Seite 1: Intro\nNeuronale Netze\n\n## Seite 2: Mehr\nGradienten\n")
    rel = f"{KURS}/W1/W01.pdf"
    (proj / "knowledge" / ".manifest.json").write_text(json.dumps({rel: {"sig": [1, 1], "klasse": "folien", "seiten": 2}}))
    s = Settings(data_dir=data, project_dir=proj)
    s.state_dir.mkdir(parents=True)
    (s.state_dir / "verarbeitet.json").write_text(json.dumps({rel: [1, 1]}))
    build_index(s.knowledge_dir, s.state_dir)
    return s


def test_quellen_status_pro_datei(settings):
    q = quellen_modul(settings, KURS)
    namen = [a["name"] for a in q["abschnitte"]]
    assert namen == ["W1", "W2"]
    status = {d["titel"]: d["status"] for a in q["abschnitte"] for d in a["dateien"]}
    assert status == {"W01.pdf": "nutzt", "scan.pdf": "scan", "code.zip": "typ", "Notebook": "link", "weg.pdf": "fehlt"}
    w01 = next(d for d in q["abschnitte"][0]["dateien"] if d["titel"] == "W01.pdf")
    assert w01["aufbereitung"] == "fertig" and w01["klasse"] == "Folien" and w01["abschnitte"] >= 1
    assert q["zusammenfassung"] == {"total": 5, "nutzt": 1, "bald": 1, "nicht": 3, "semantisch": 0,
                                    "aufbereitet": 1, "aufbereitung_offen": 0, "uebersprungen": 0,
                                    "ausgeschlossen": 0}


def test_quellen_anderer_kurs_und_ohne_index(settings, tmp_path):
    (settings.state_dir / "suche.db").unlink()
    q = quellen_modul(settings, KURS)
    assert {d["status"] for a in q["abschnitte"] for d in a["dateien"]} >= {"bald"}  # ausgelesen, nicht im Index
    assert quellen_modul(settings, "Gibt es nicht")["zusammenfassung"]["total"] == 0


def test_aktualisierung_laeuft_alle_schritte_und_meldet_fehler(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_moodle, "LOG", tmp_path / "log" / "m.log")
    aufrufe = []

    def fake_run(cmd, **kw):
        aufrufe.append(cmd[1] if cmd[0] != "moodle-dl" else "moodle")
        assert kw["stdin"] == subprocess.DEVNULL and kw["env"]["STUDY_DATA_DIR"] == str(settings.data_dir)
        return SimpleNamespace(returncode=1 if cmd[0] == "moodle-dl" else 0)

    routes_moodle._zustand.update(status="läuft", schritte=[{"key": k, "titel": t, "status": "wartet"}
                                                            for k, t in routes_moodle.SCHRITTE])
    nachher = []
    routes_moodle.ausfuehren(settings, routes_moodle.befehle(settings, "moodle-dl"), lambda: nachher.append(1), fake_run)
    z = routes_moodle.zustand()
    assert aufrufe == ["moodle", "convert", "index", "rag-index"]  # Moodle scheitert, lokale Schritte laufen weiter
    assert z["status"] == "fehler" and z["fehler"] == ["moodle"] and z["neue_dateien"] == 0 and nachher == [1]
    assert [s["status"] for s in z["schritte"]] == ["fehler", "fertig", "fertig", "fertig"]
    assert "content_fileurl" not in json.dumps(z)


def test_aktualisierung_startet_nicht_doppelt(settings, monkeypatch):
    monkeypatch.setattr(routes_moodle, "taeglicher_lauf_aktiv", lambda: False)
    routes_moodle._zustand.update(status="läuft")
    with pytest.raises(ValueError, match="läuft schon"):
        routes_moodle.starten(settings)
    routes_moodle._zustand.update(status="bereit")
    monkeypatch.setattr(routes_moodle, "taeglicher_lauf_aktiv", lambda: True)
    with pytest.raises(ValueError, match="tägliche Lauf"):
        routes_moodle.starten(settings)


def test_befehle_nehmen_budget_aus_einstellungen(settings):
    from study_agent import einstellungen
    einstellungen.speichern(settings.state_dir, {"verarbeitung": {"ocr_pro_lauf": 0, "rag_max": 50}})
    cmds = routes_moodle.befehle(settings, "/bin/moodle-dl")
    assert cmds["moodle"] == ["/bin/moodle-dl", "-p", str(settings.data_dir)]
    assert cmds["convert"][-2:] == ["--ocr", "0"] and cmds["rag"][-2:] == ["--max", "50"]


def test_ausschluss_entfernt_aus_suche_und_verarbeitung(settings):
    import sqlite3

    from study_agent.pipeline import ausschluss
    rel = f"{KURS}/W1/W01.pdf"
    ausschluss.setzen(settings.state_dir, [rel], nutzen=False)
    build_index(settings.knowledge_dir, settings.state_dir)
    con = sqlite3.connect(settings.state_dir / "suche.db")
    assert con.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0
    d = next(d for a in quellen_modul(settings, KURS)["abschnitte"] for d in a["dateien"] if d["rel"] == rel)
    assert d["status"] == "aus" and d["nutzen"] is False and d["geladen"] and d["ausgelesen"]
    ausschluss.setzen(settings.state_dir, [rel], nutzen=True)
    build_index(settings.knowledge_dir, settings.state_dir)
    assert con.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 1
    with pytest.raises(ValueError):
        ausschluss.setzen(settings.state_dir, ["../x"], nutzen=False)


def test_wichtige_daten_ohne_lektionen_und_doppelte():
    from study_agent.server.dashboard.routes_modul import wichtige_daten
    d = wichtige_daten(
        ["2026-09-16", "2026-10-07", "2026-12-18 Projekttagabgabe:", "2026-12-18 Projekttabgabe"],
        [{"kind": "abgabe", "due": "2026-12-18 11:30:00+00:00", "name": "Upload Projekt"},
         {"kind": "lektion", "due": "2026-11-23 07:15:00+00:00", "name": "Lektion"},
         {"kind": "praesentation", "due": "2026-11-23 22:59:00+00:00", "name": "Abschlusspräsentation"}],
        "2026-11-16")
    assert [(e["datum"], e["text"]) for e in d] == [
        ("2026-11-23", "Abschlusspräsentation"), ("2026-12-18", "Upload Projekt"), ("2026-12-18", "Projekttagabgabe")]


def test_vorschau_nur_fuer_bekannte_dateien(settings):
    from study_agent.pipeline.quellen import vorschau
    v = vorschau(settings, f"{KURS}/W1/W01.pdf")
    assert "Neuronale Netze" in v["text"] and not v["gekuerzt"]
    for rel in ("../../etc/passwd", f"{KURS}/W1/scan.pdf", "config.json"):
        with pytest.raises(ValueError):
            vorschau(settings, rel)
