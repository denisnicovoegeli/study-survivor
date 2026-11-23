from datetime import date
from pathlib import Path

import openpyxl
import pytest

from study_agent.pipeline import module, pruefungsplan
from study_agent.server.dashboard import routes_studium as rs


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "moodle"
    (d / "26HS Deep Learning BAI").mkdir(parents=True)
    (d / "Generative KI & Agentensysteme 26H2").mkdir()
    (d / "_eigene" / "26HS Deep Learning BAI").mkdir(parents=True)  # Teams-Material zu Moodle-Kurs
    return d


def test_eigene_module_ohne_moodle_kurse(data_dir):
    assert module.eigene_module(data_dir) == []
    assert module.modul_anlegen(data_dir, " Statistik ") == "Statistik"
    assert module.eigene_module(data_dir) == ["Statistik"]


@pytest.mark.parametrize("name", ["", "..", "a/b", ".versteckt", "statistik", "26hs deep learning bai"])
def test_modul_anlegen_ungueltig(data_dir, name):
    module.modul_anlegen(data_dir, "Statistik")
    with pytest.raises(ValueError):
        module.modul_anlegen(data_dir, name)


def test_modul_entfernen_nur_leer(data_dir):
    module.modul_anlegen(data_dir, "Statistik")
    (data_dir / "_eigene" / "Statistik" / "W1.pdf").write_bytes(b"%PDF")
    with pytest.raises(ValueError):
        module.modul_entfernen(data_dir, "Statistik")
    (data_dir / "_eigene" / "Statistik" / "W1.pdf").unlink()
    (data_dir / "_eigene" / "Statistik" / ".DS_Store").write_bytes(b"x")
    module.modul_entfernen(data_dir, "Statistik")
    assert module.eigene_module(data_dir) == []
    with pytest.raises(ValueError):
        module.modul_entfernen(data_dir, "26HS Deep Learning BAI")  # Moodle-Kurs nie


def _plan(pfad: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Titel des Plans"])
    ws.append(["Tag\nDatum", "Zeit\nTime", "Dauer Min.", "Anlass-Nr.", "Modul bzw. Kurs", "Verantwortliche Dozierende",
               "Studiengang", "Modell/Klasse"])
    ws.append(["Samstag, 09.01.2027", "09.00 - 10.00", 60, "A-1", "Deep Learning", "Suter", "BAI", "VZ + TZ"])
    ws.append(["Montag, 11.01.2027", "08.15 - 21.00", None, "A-2", "Generative KI & Agentensysteme mündlich (Einteilung)",
               "Martin", "BAI", "VZ + TZ"])
    ws.append(["Dienstag, 12.01.2027", "10.00 - 11.00", 60, "B-1", "Deep Learning", "X", "WI", "VZ"])
    ws.append(["Dienstag, 12.01.2027", "10.00 - 11.00", 60, "B-2", "Marketing Management", "Y", "BAI", "VZ"])
    ws.append([None, None, None, None, None, None, None, None])
    wb.save(pfad)


def test_pruefungsplan_lesen_und_zuordnen(tmp_path, data_dir):
    pfad = tmp_path / "plan.xlsx"
    _plan(pfad)
    pr = pruefungsplan.lesen(pfad)
    assert [p.datum for p in pr] == [date(2027, 1, 9), date(2027, 1, 11), date(2027, 1, 12), date(2027, 1, 12)]
    assert pr[0].termin("plan.xlsx") == {"datum": "2027-01-09", "titel": "Prüfung: Deep Learning (09.00–10.00 Uhr, 60 Min.)",
                                         "art": "pruefung", "quelle": "plan.xlsx, Anlass A-1", "zeit": "09:00"}
    assert "zeit" not in pr[1].termin("plan.xlsx")  # Zeitfenster ohne Dauer: ganztägig
    v = pruefungsplan.vorschlag(pr, module.moodle_kurse(data_dir) + ["Marketing-Modul BAI 2026"])
    assert v["studiengang"] == "BAI"
    assert v["zuordnung"] == {0: "26HS Deep Learning BAI", 1: "Generative KI & Agentensysteme 26H2", 2: None, 3: None}


def test_pruefungsplan_ohne_kopfzeile(tmp_path):
    pfad = tmp_path / "x.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    wb.save(pfad)
    with pytest.raises(ValueError):
        pruefungsplan.lesen(pfad)


def test_import_traegt_ein_und_doppelt_nicht(tmp_path, data_dir):
    projekt = tmp_path / "projekt"
    (projekt / "studium").mkdir(parents=True)
    _plan(projekt / "studium" / "plan.xlsx")
    eintrag = [{"index": 0, "modul": "26HS Deep Learning BAI"}]
    out = rs.pruefungsplan_importieren(projekt, data_dir, "plan.xlsx", eintrag)
    assert len(out["neu"]) == 1
    assert rs.pruefungsplan_importieren(projekt, data_dir, "plan.xlsx", eintrag) == {"neu": [], "schon_vorhanden": [0]}
    lesen = rs.pruefungsplan_lesen(projekt, data_dir, "plan.xlsx")
    assert lesen["pruefungen"][0]["vorhanden"] is True
    with pytest.raises(ValueError):
        rs.pruefungsplan_importieren(projekt, data_dir, "plan.xlsx", [{"index": 0, "modul": "Erfunden"}])


def test_studium_dateien(tmp_path):
    assert rs.studium_speichern(tmp_path, "Reglement.pdf", b"%PDF") == "Reglement.pdf"
    assert rs.studium_speichern(tmp_path, "../Reglement.pdf", b"%PDF") == "Reglement-2.pdf"
    with pytest.raises(ValueError):
        rs.studium_speichern(tmp_path, "virus.exe", b"x")
    with pytest.raises(ValueError):
        rs.studium_datei(tmp_path, "../geheim.txt")
    rs.studium_entfernen(tmp_path, "Reglement.pdf")
    assert [d["name"] for d in rs.studium_liste(tmp_path)] == ["Reglement-2.pdf"]
