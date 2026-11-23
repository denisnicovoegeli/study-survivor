"""Moodle von Hand aktualisieren: moodle-dl → convert → Suchindex → semantischer Index, im Hintergrund.

Gleiche Schritte wie der Anfang von scripts/daily.sh, aber ohne Aufbereitung durch das Modell
(die startet weiterhin der tägliche Lauf oder der Knopf «verarbeiten»). Die Ausgabe der Befehle
landet nur in logs/moodle-aktualisieren.log; ans Dashboard gehen Schrittnamen und Exit-Codes,
damit nie eine URL mit Token aus moodle-dl im Browser auftaucht.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from study_agent import einstellungen
from study_agent.config import REPO_DIR, Settings

SCHRITTE = [
    ("moodle", "Moodle abfragen"),
    ("convert", "Text auslesen"),
    ("index", "Suchindex"),
    ("rag", "Semantische Suche"),
]
TIMEOUT = {"moodle": 20 * 60, "convert": 20 * 60, "index": 5 * 60, "rag": 20 * 60}
LOG = REPO_DIR / "logs" / "moodle-aktualisieren.log"

_lock = threading.Lock()
_zustand: dict[str, Any] = {"status": "bereit"}


def moodle_dl_pfad() -> str | None:
    """Wie scripts/daily.sh: $MOODLE_DL, dann die venv unter ~/.local/share, dann PATH."""
    for kandidat in (os.environ.get("MOODLE_DL"),
                     str(Path.home() / ".local/share/moodle-dl-venv/bin/moodle-dl"),
                     shutil.which("moodle-dl")):
        if kandidat and os.access(kandidat, os.X_OK):
            return kandidat
    return None


def study_pfad() -> str:
    neben = Path(sys.executable).with_name("study")
    return str(neben) if neben.exists() else str(REPO_DIR / ".venv" / "bin" / "study")


def taeglicher_lauf_aktiv() -> bool:
    try:
        return subprocess.run(["pgrep", "-f", "scripts/daily.sh"], capture_output=True).returncode == 0
    except OSError:
        return False


def zustand() -> dict[str, Any]:
    with _lock:
        return {**_zustand, "schritte": [dict(s) for s in _zustand.get("schritte", [])]}


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zaehlen(settings: Settings) -> tuple[int, int]:
    """(Dateien in Moodle, umgewandelte Dateien), um neue Dateien nach dem Lauf zu melden."""
    from study_agent.pipeline.convert import load_manifest
    from study_agent.pipeline.moodle_db import MoodleDbError, all_files
    try:
        moodle = len(all_files(settings.moodle_db))
    except MoodleDbError:
        moodle = 0
    return moodle, len(load_manifest(settings.knowledge_dir))


def befehle(settings: Settings, moodle_dl: str) -> dict[str, list[str]]:
    v = einstellungen.laden(settings.state_dir)["verarbeitung"]
    study = study_pfad()
    return {
        "moodle": [moodle_dl, "-p", str(settings.data_dir)],
        "convert": [study, "convert", "--current", "--ocr", str(v.get("ocr_pro_lauf", 1))],
        "index": [study, "index"],
        "rag": [study, "rag-index", "--max", str(v.get("rag_max", 600))],
    }


def _setzen(**werte) -> None:
    with _lock:
        _zustand.update(werte)


def _schritt_setzen(i: int, **werte) -> None:
    with _lock:
        _zustand["schritte"][i].update(werte)


def ausfuehren(settings: Settings, cmds: dict[str, list[str]], nachher: Callable[[], None] | None = None,
               run: Callable[..., Any] = subprocess.run) -> None:
    """Führt die Schritte nacheinander aus. Scheitert Moodle, laufen die übrigen trotzdem (lokaler Stand)."""
    vorher = _zaehlen(settings)
    env = {**os.environ, "STUDY_DATA_DIR": str(settings.data_dir), "STUDY_PROJECT_DIR": str(settings.project_dir)}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    fehler = []
    with open(LOG, "a") as log:
        log.write(f"=== {_jetzt()} (Dashboard)\n")
        for i, (key, _) in enumerate(SCHRITTE):
            _schritt_setzen(i, status="läuft")
            log.write(f"--- {key}\n")
            log.flush()
            try:
                rc = run(cmds[key], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         cwd=str(REPO_DIR), env=env, timeout=TIMEOUT[key]).returncode
            except subprocess.TimeoutExpired:
                rc = "Zeitlimit"
            except OSError as exc:
                rc = type(exc).__name__
            ok = rc == 0
            _schritt_setzen(i, status="fertig" if ok else "fehler", exit=None if ok else rc)
            if not ok:
                fehler.append(key)
            log.write(f"{key}: {rc}\n")
        log.write(f"=== Ende {_jetzt()}\n")
    nach = _zaehlen(settings)
    if nachher:
        try:
            nachher()
        except Exception:  # noqa: BLE001 Cache leeren darf den Lauf nicht scheitern lassen
            pass
    _setzen(status="fehler" if fehler else "fertig", beendet=_jetzt(), fehler=fehler,
            neue_dateien=max(0, nach[0] - vorher[0]), neu_umgewandelt=max(0, nach[1] - vorher[1]))


def starten(settings: Settings, nachher: Callable[[], None] | None = None) -> dict[str, Any]:
    """Startet einen Lauf im Hintergrund. ValueError, wenn schon einer läuft oder moodle-dl fehlt."""
    with _lock:
        if _zustand.get("status") == "läuft":
            raise ValueError("Die Aktualisierung läuft schon.")
    if taeglicher_lauf_aktiv():
        raise ValueError("Der tägliche Lauf ist gerade aktiv und holt Moodle schon. Versuch es danach nochmals.")
    moodle_dl = moodle_dl_pfad()
    if not moodle_dl:
        raise ValueError("moodle-dl nicht gefunden (MOODLE_DL setzen oder unter ~/.local/share/moodle-dl-venv installieren).")
    cmds = befehle(settings, moodle_dl)
    _setzen(status="läuft", gestartet=_jetzt(), beendet=None, fehler=[], neue_dateien=None, neu_umgewandelt=None,
            schritte=[{"key": k, "titel": t, "status": "wartet"} for k, t in SCHRITTE])
    threading.Thread(target=ausfuehren, args=(settings, cmds, nachher), daemon=True).start()
    return zustand()


def _dense_nachfuehren(settings: Settings, kurs: str) -> None:
    """Semantischen Index eines Kurses an den Volltext-Index angleichen (entfernt und ergänzt Chunks)."""
    try:
        from study_agent.agent.rag import build_dense_index
        build_dense_index(settings, kurs=kurs, max_neu=300, log=lambda *a, **k: None)
    except Exception:  # noqa: BLE001 der tägliche Lauf gleicht ohnehin ab
        pass


def register_routes(router: Any, get_settings_fn: Any, cached_study: Any, cache_invalidate_fn: Callable) -> None:
    from fastapi import Body, HTTPException, Query

    from study_agent.pipeline.classify import load_overrides
    from study_agent.pipeline.quellen import quellen_modul

    def nachher():
        cache_invalidate_fn("pending", "new-files", "courses", "files_tree", "deadlines", "termine", "grades")

    @router.get("/moodle/aktualisieren")
    def get_aktualisieren():
        return zustand()

    @router.post("/moodle/aktualisieren")
    def post_aktualisieren():
        try:
            return starten(get_settings_fn(), nachher)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.put("/quellen/nutzen")
    def put_nutzen(payload: dict = Body(...)):
        """Häkchen «Nutzen»: Volltext-Index sofort, semantischer Index im Hintergrund."""
        from study_agent.pipeline import ausschluss
        from study_agent.pipeline.suche import build_index

        s = get_settings_fn()
        rels = [str(r) for r in payload.get("rels") or []]
        kurs = str(payload.get("kurs") or "")
        if not rels or not kurs:
            raise HTTPException(400, "rels und kurs fehlen")
        try:
            aus = ausschluss.setzen(s.state_dir, rels, bool(payload.get("nutzen")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        build_index(s.knowledge_dir, s.state_dir)
        threading.Thread(target=_dense_nachfuehren, args=(s, kurs), daemon=True).start()
        cache_invalidate_fn("pending")
        return {"ausgeschlossen": len(aus)}

    @router.get("/quellen/vorschau")
    def get_vorschau(rel: str = Query(...)):
        """Ausgelesener Text einer Datei (Anfang), nur für Einträge aus knowledge/.manifest.json."""
        from study_agent.pipeline.quellen import vorschau

        try:
            return vorschau(get_settings_fn(), rel)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/quellen")
    def get_quellen(kurs: str = Query(...)):
        s = get_settings_fn()
        overrides, _ = load_overrides(s.klassen_path)
        return quellen_modul(s, kurs, overrides)
