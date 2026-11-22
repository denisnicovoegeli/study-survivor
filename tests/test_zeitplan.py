import plistlib
import subprocess

import pytest

from study_agent import einstellungen, zeitplan


@pytest.fixture
def fake_launchctl(monkeypatch, tmp_path):
    """launchctl nie wirklich aufrufen; plist landet in tmp_path."""
    aufrufe = []

    def run(*args):
        aufrufe.append(args)
        rc = 0 if args[0] in ("bootstrap", "bootout", "disable") else 1
        return subprocess.CompletedProcess(args, rc, "", "")

    monkeypatch.setattr(zeitplan, "_launchctl", run)
    monkeypatch.setattr(zeitplan.Path, "home", lambda: tmp_path)
    return aufrufe


def test_plist_taeglich_ohne_wochentag(tmp_path):
    z = {"aktiv": True, "zeit": "07:30", "tage": list(einstellungen.TAGE)}
    d = zeitplan.plist_daten(z, tmp_path)
    assert d["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    assert d["ProgramArguments"] == [str(tmp_path / "scripts" / "daily.sh")]


def test_plist_wochentage_launchd_nummern(tmp_path):
    z = {"aktiv": True, "zeit": "18:05", "tage": ["mo", "so"]}
    intervall = zeitplan.plist_daten(z, tmp_path)["StartCalendarInterval"]
    assert intervall == [{"Weekday": 1, "Hour": 18, "Minute": 5}, {"Weekday": 0, "Hour": 18, "Minute": 5}]


def test_anwenden_schreibt_und_laedt(fake_launchctl, tmp_path):
    z = {"aktiv": True, "zeit": "08:00", "tage": ["mo", "mi"]}
    zeitplan.anwenden(z, tmp_path)
    plist = plistlib.loads(zeitplan.plist_pfad().read_bytes())
    assert plist == zeitplan.plist_daten(z, tmp_path)
    assert ("bootstrap", zeitplan._domain(), str(zeitplan.plist_pfad())) in fake_launchctl


def test_anwenden_aus_entfernt_job(fake_launchctl, tmp_path):
    zeitplan.anwenden({"aktiv": True, "zeit": "08:00", "tage": ["mo"]}, tmp_path)
    zeitplan.anwenden({"aktiv": False, "zeit": "08:00", "tage": ["mo"]}, tmp_path)
    assert not zeitplan.plist_pfad().exists()
    assert fake_launchctl[-1][0] == "print"  # zuletzt nur Status, kein bootstrap


def test_aktiv_ohne_tage_ungueltig(tmp_path):
    with pytest.raises(ValueError):
        einstellungen.speichern(tmp_path, {"zeitplan": {"aktiv": True, "tage": []}})
    assert einstellungen.speichern(tmp_path, {"zeitplan": {"aktiv": False, "tage": []}})["zeitplan"]["tage"] == []


def test_letzter_lauf(tmp_path):
    log = tmp_path / "daily.log"
    log.write_text(
        "=== 2026-11-13 08:00:01 ===\n--- moodle-dl\n=== Ende 2026-11-13 08:20:00, Fehler: 0\n"
        "=== übersprungen 2026-11-13 09:00:00: heute schon gelaufen\n"
        "=== 2026-11-14 08:00:02 ===\n--- index\nindex: Exit 2\n=== Ende 2026-11-14 08:30:00, Fehler: 1\n"
    )
    lauf = zeitplan.letzter_lauf(log)
    assert lauf == {"start": "2026-11-14 08:00:02", "ende": "2026-11-14 08:30:00", "fehler": 1,
                    "schritte_fehler": ["index"]}
    assert zeitplan.letzter_lauf(tmp_path / "fehlt.log") is None
