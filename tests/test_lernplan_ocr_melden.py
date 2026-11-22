"""Etappe 4: Lernplan, Texterkennung, Benachrichtigungen, Semester-Archiv."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from study_agent import benachrichtigung, einstellungen
from study_agent.pipeline import lernplan, ocr
from study_agent.pipeline.convert import convert_tree, load_manifest
from study_agent.pipeline.pdf_pages import PageInfo


# --- Lernplan ---------------------------------------------------------------

def _themen(n):
    return [lernplan.Thema(f"W{i}", f"Thema {i}", True) for i in range(1, n + 1)]


def test_thema_name_entfernt_html_reste():
    assert lernplan.thema_name("＜span class=＂x＂＞1 Generative AI＜⧸span＞") == "1 Generative AI"
    assert lernplan.thema_name("Woche 1： Bausteine") == "Woche 1: Bausteine"


def test_themen_aus_wochen_ohne_allgemein_und_leere():
    wochen = [{"section": "Allgemein", "total": 3, "verarbeitet": 1},
              {"section": "W1", "total": 2, "verarbeitet": 0},
              {"section": "W2", "total": 0, "verarbeitet": 0}]
    assert [t.id for t in lernplan.themen_aus_wochen(wochen)] == ["W1"]


def test_modul_plan_verteilt_bis_vor_die_pruefung():
    heute = date(2026, 11, 16)  # Montag
    plan = lernplan.modul_plan(_themen(6), date(2027, 1, 9), heute, set())
    assert plan[0]["start"] == "2026-11-16" and plan[-1]["start"] == "2027-01-04"
    assert plan[-1]["wiederholung"] and plan[-1]["pruefung"] == "2027-01-09" and plan[-1]["themen"] == []
    verteilt = [t["id"] for w in plan for t in w["themen"]]
    assert verteilt == [f"W{i}" for i in range(1, 7)]  # alle, in Reihenfolge, je einmal
    assert not any(w["wiederholung"] for w in plan[:-1])


def test_modul_plan_pruefung_am_montag_wiederholt_schon_die_woche_davor():
    plan = lernplan.modul_plan(_themen(2), date(2027, 1, 11), date(2026, 12, 14), set())
    assert [w["wiederholung"] for w in plan] == [False, False, False, True, True]
    assert plan[-1]["pruefung"] == "2027-01-11"


def test_modul_plan_ohne_erledigte_und_nach_der_pruefung_leer():
    plan = lernplan.modul_plan(_themen(3), date(2026, 12, 20), date(2026, 11, 30), {"W2"})
    assert [t["id"] for w in plan for t in w["themen"]] == ["W1", "W3"]
    assert lernplan.modul_plan(_themen(3), date(2026, 1, 1), date(2026, 11, 30), set()) == []


def test_modul_plan_pruefung_diese_woche():
    plan = lernplan.modul_plan(_themen(2), date(2026, 11, 20), date(2026, 11, 18), set())
    assert len(plan) == 1 and plan[0]["wiederholung"] and len(plan[0]["themen"]) == 2


def test_erledigt_setzen_und_zusammenfuehren(tmp_path):
    assert lernplan.erledigt_setzen(tmp_path, "DL", "W1", True) == ["W1"]
    assert lernplan.laden(tmp_path) == {"DL": ["W1"]}
    assert lernplan.erledigt_setzen(tmp_path, "DL", "W1", False) == []
    assert lernplan.laden(tmp_path) == {}
    heute = date(2026, 11, 16)
    w = lernplan.zusammenfuehren({
        "B": lernplan.modul_plan(_themen(1), date(2026, 11, 28), heute, set()),
        "A": lernplan.modul_plan(_themen(1), date(2026, 11, 20), heute, set()),
    })
    assert w[0]["start"] == "2026-11-16" and [m["modul"] for m in w[0]["module"]] == ["A", "B"]


def test_themen_reihenfolge_und_doppelte():
    wochen = [{"section": "＜span＞11 Tokenizer＜⧸span＞", "total": 1, "verarbeitet": 1},
              {"section": "11 Tokenizer", "total": 2, "verarbeitet": 0},
              {"section": "Folien", "total": 1, "verarbeitet": 0},
              {"section": "2 Context", "total": 1, "verarbeitet": 0},
              {"section": "1 GenAI", "total": 1, "verarbeitet": 0}]
    ordnung = lernplan.reihenfolge("# K\n## Allgemeines\n## 1 GenAI\n## Folien\n## 11 Tokenizer\n## 2 Context\n")
    themen = lernplan.themen_aus_wochen(wochen, ordnung)
    assert [t.name for t in themen] == ["1 GenAI", "Folien", "2 Context", "11 Tokenizer"]
    assert themen[-1].aufbereitet  # eine der beiden Schreibweisen ist aufbereitet


def test_plan_startet_am_wochenende_naechste_woche():
    plan = lernplan.modul_plan(_themen(2), date(2026, 12, 4), date(2026, 11, 15), set())  # Sonntag
    assert plan[0]["start"] == "2026-11-16"
    assert lernplan.modul_plan(_themen(1), date(2026, 11, 15), date(2026, 11, 14), set())[0]["pruefung"]


def test_karten_stand():
    assert lernplan.karten_stand([{"box": 1}, {}, {"box": 3}]) == {"total": 3, "fach1": 2, "fach2": 0, "fach3": 1}


# --- Texterkennung ----------------------------------------------------------

def test_zerlegen_nach_kopfzeilen():
    text = "=== Seite 3 ===\nA\n=== Seite 4 ===\nB\n=== Seite 9 ===\nfremd"
    assert ocr.zerlegen(text, [3, 4]) == {3: "A", 4: "B"}
    assert ocr.zerlegen("nur Text", [5, 6]) == {5: "nur Text"}


def test_ocr_pages_in_gruppen():
    bilder = [(i, b"png", True) for i in range(1, 7)]
    aufrufe = []

    def fake(gruppe):
        aufrufe.append([nr for nr, _ in gruppe])
        return "\n".join(f"=== Seite {nr} ===\n# Titel {nr}\nText {nr}" for nr, _ in gruppe)

    pages = ocr.ocr_pages(Path("x.pdf"), fake, bilder)
    assert aufrufe == [[1, 2, 3, 4], [5, 6]]
    assert pages[0].title == "Titel 1" and "Text 6" in pages[5].text and all(p.visual for p in pages)


def test_ocr_titel_ohne_vorlagenzeilen():
    bilder = [(i, b"png", True) for i in range(1, 5)]
    fake = lambda g: "\n".join(f"=== Seite {nr} ===\nST\nKOPF\nThema {nr}" for nr, _ in g)  # noqa: E731
    assert [p.title for p in ocr.ocr_pages(Path("x.pdf"), fake, bilder)] == [f"Thema {i}" for i in range(1, 5)]


def _scan(tmp_path):
    src = tmp_path / "src" / "Kurs"
    src.mkdir(parents=True)
    (src / "scan.pdf").write_bytes(b"%PDF")
    leer = lambda path: [PageInfo(1, "", "", True, 1.0, 0, True)]  # noqa: E731
    gelesen = lambda path: [PageInfo(1, "Titel", "Erkannter Text", True, 1.0, 0, True)]  # noqa: E731
    return tmp_path / "src", leer, gelesen


def test_convert_ohne_ocr_meldet_scan(tmp_path):
    src, leer, _ = _scan(tmp_path)
    r = convert_tree(src, tmp_path / "k", lambda p: "", leer)
    assert r.converted == [] and r.failed[0][1] == "kein Text extrahiert (gescannt?)"


def test_convert_mit_ocr_schreibt_text_und_markiert_manifest(tmp_path):
    src, leer, gelesen = _scan(tmp_path)
    r = convert_tree(src, tmp_path / "k", lambda p: "", leer, ocr=gelesen, ocr_limit=1)
    assert r.ocr == ["Kurs/scan.pdf"] and r.failed == []
    md = (tmp_path / "k" / "Kurs" / "scan.pdf.md").read_text()
    assert "Erkannter Text" in md and "texterkennung: vision" in md
    assert load_manifest(tmp_path / "k")["Kurs/scan.pdf"]["ocr"] is True


def test_convert_ocr_budget(tmp_path):
    src, leer, gelesen = _scan(tmp_path)
    (src / "Kurs" / "scan2.pdf").write_bytes(b"%PDF")
    r = convert_tree(src, tmp_path / "k", lambda p: "", leer, ocr=gelesen, ocr_limit=1)
    assert len(r.ocr) == 1 and r.failed[0][1].endswith("Texterkennung: nicht in diesem Lauf")


def test_convert_ocr_fehler_bleibt_offen(tmp_path):
    src, leer, _ = _scan(tmp_path)

    def kaputt(path):
        raise TimeoutError("Proxy")

    r = convert_tree(src, tmp_path / "k", lambda p: "", leer, ocr=kaputt, ocr_limit=1)
    assert "Texterkennung: TimeoutError" in r.failed[0][1] and r.converted == []


# --- Benachrichtigungen -----------------------------------------------------

NOW = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
B = einstellungen.DEFAULTS["benachrichtigungen"]


def test_meldung_bauen():
    fristen = [("DL: Projekt", NOW + timedelta(days=1)), ("GenKI: Quiz", NOW + timedelta(days=2)),
               ("Weit weg", NOW + timedelta(days=20))]
    m = benachrichtigung.meldung_bauen(B, 2, fristen, 1, NOW)
    assert m.text == "2 neue Dateien · DL: Projekt morgen (+1 weitere) · 1 Freigabe wartet" and m.wichtig


def test_meldung_bauen_nichts_zu_melden_und_abgeschaltet():
    assert benachrichtigung.meldung_bauen(B, 0, [], 0, NOW) is None
    aus = {**B, "neues_material": False, "freigaben": False}
    assert benachrichtigung.meldung_bauen(aus, 5, [], 3, NOW) is None


def test_ntfy_sendet_post(monkeypatch):
    gesendet = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout):
        gesendet.update(url=req.full_url, data=req.data, prio=req.get_header("Priority"))
        return Resp()

    monkeypatch.setattr(benachrichtigung.urllib.request, "urlopen", fake_urlopen)
    out = benachrichtigung.senden(benachrichtigung.Meldung("T", "Hallo ä", True),
                                  {**B, "mac": False, "ntfy_thema": "mein-thema"})
    assert out == {"ntfy": True}
    assert gesendet == {"url": "https://ntfy.sh/mein-thema", "data": "Hallo ä".encode(), "prio": "high"}


def test_ntfy_fehler_wird_gemeldet(monkeypatch):
    def kaputt(req, timeout):
        raise OSError("offline")

    monkeypatch.setattr(benachrichtigung.urllib.request, "urlopen", kaputt)
    out = benachrichtigung.senden(benachrichtigung.Meldung("T", "x"), {**B, "mac": False, "ntfy_thema": "t"})
    assert out["ntfy"] is False and "offline" in out["ntfy_fehler"]


# --- Einstellungen ----------------------------------------------------------

@pytest.mark.parametrize("feld,wert", [
    ("ntfy_thema", "mit leerzeichen"), ("ntfy_server", "http://example.com"), ("frist_tage", 0), ("mac", "ja"),
])
def test_benachrichtigungen_validierung(feld, wert):
    with pytest.raises(ValueError):
        einstellungen.validieren({"benachrichtigungen": {feld: wert}})


def test_archiv_ueberspringt_dateien(tmp_path):
    e = einstellungen.validieren({"semester": {"archiv": ["Alt", "Alt"]}})
    assert e["semester"]["archiv"] == ["Alt"]
    filt = {**e["filter"], "archiv": e["semester"]["archiv"]}
    assert einstellungen.ueberspringen_grund(filt, "Alt", "a.pdf", tmp_path / "a.pdf", "folien") == "Modul archiviert"
    assert einstellungen.ueberspringen_grund(filt, "Neu", "a.pdf", tmp_path / "a.pdf", "folien") is None
