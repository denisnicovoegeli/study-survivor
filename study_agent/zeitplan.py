"""Täglicher Lauf als launchd-Job, geschrieben aus den Einstellungen (zeitplan.*).

Höchstens ein Lauf pro Tag: eine Uhrzeit, wählbare Wochentage, ein/aus.
daily.sh prüft zusätzlich, ob heute schon gelaufen wurde.
"""
import os
import plistlib
import re
import subprocess
from datetime import datetime
from pathlib import Path

from study_agent.einstellungen import TAGE

LABEL = "ch.fhnw.study-survivor"
ALT_LABEL = "ch.fhnw.study-agent"
REPO = Path(__file__).resolve().parents[1]
# launchd: 0 = Sonntag, 1 = Montag … 6 = Samstag
_WOCHENTAG = {"so": 0, "mo": 1, "di": 2, "mi": 3, "do": 4, "fr": 5, "sa": 6}


def plist_pfad() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def plist_daten(zeitplan: dict, repo: Path = REPO) -> dict:
    stunde, minute = (int(x) for x in zeitplan["zeit"].split(":"))
    tage = [t for t in TAGE if t in zeitplan["tage"]]
    if len(tage) == len(TAGE):
        intervall: object = {"Hour": stunde, "Minute": minute}
    else:
        intervall = [{"Weekday": _WOCHENTAG[t], "Hour": stunde, "Minute": minute} for t in tage]
    return {
        "Label": LABEL,
        "ProgramArguments": [str(repo / "scripts" / "daily.sh")],
        "WorkingDirectory": str(repo),
        "StartCalendarInterval": intervall,
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def anwenden(zeitplan: dict, repo: Path = REPO) -> dict:
    """Schreibt und lädt den Job (aktiv mit Tagen) oder entlädt und entfernt ihn."""
    ziel = plist_pfad()
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if not zeitplan["aktiv"] or not zeitplan["tage"]:
        ziel.unlink(missing_ok=True)
        return status(zeitplan, repo)
    alt = alten_job_deaktivieren()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_suffix(".tmp")
    tmp.write_bytes(plistlib.dumps(plist_daten(zeitplan, repo)))
    tmp.replace(ziel)
    r = _launchctl("bootstrap", _domain(), str(ziel))
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap fehlgeschlagen: {(r.stderr or r.stdout).strip()}")
    return status(zeitplan, repo) | {"alter_job_deaktiviert": alt}


def alten_job_deaktivieren() -> bool:
    """Entlädt den Vorgänger-Job, damit nicht zwei Läufe Moodle laden. True, wenn es ihn gab."""
    alt = Path.home() / "Library" / "LaunchAgents" / f"{ALT_LABEL}.plist"
    if not alt.exists():
        return False
    _launchctl("bootout", f"{_domain()}/{ALT_LABEL}")
    _launchctl("disable", f"{_domain()}/{ALT_LABEL}")
    return True


_START = re.compile(r"^=== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ===$")
_ENDE = re.compile(r"^=== Ende (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d), Fehler: (\d+)$")
_SCHRITT_FEHLER = re.compile(r"^(\S+): Exit (\d+)$")


def letzter_lauf(log: Path) -> dict | None:
    """Liest den letzten Lauf aus logs/daily.log: Start, Ende, Fehler, fehlgeschlagene Schritte."""
    try:
        with log.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 64_000))
            zeilen = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for i in range(len(zeilen) - 1, -1, -1):
        m = _START.match(zeilen[i])
        if not m:
            continue
        lauf: dict = {"start": m.group(1), "ende": None, "fehler": None, "schritte_fehler": []}
        for z in zeilen[i + 1:]:
            if e := _ENDE.match(z):
                lauf["ende"], lauf["fehler"] = e.group(1), int(e.group(2))
            elif s := _SCHRITT_FEHLER.match(z):
                lauf["schritte_fehler"].append(s.group(1))
        return lauf
    return None


def status(zeitplan: dict, repo: Path = REPO) -> dict:
    eingerichtet = plist_pfad().exists()
    geladen = _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0
    return {
        "eingerichtet": eingerichtet,
        "geladen": geladen,
        "stimmt": eingerichtet and geladen and _plist_stimmt(zeitplan, repo),
        "letzter_lauf": letzter_lauf(repo / "logs" / "daily.log"),
        "jetzt": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _plist_stimmt(zeitplan: dict, repo: Path) -> bool:
    try:
        vorhanden = plistlib.loads(plist_pfad().read_bytes())
    except (OSError, plistlib.InvalidFileException):
        return False
    return vorhanden == plist_daten(zeitplan, repo)
