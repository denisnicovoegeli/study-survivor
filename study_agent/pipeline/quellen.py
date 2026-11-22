"""Quellen eines Moduls: jede Datei aus Moodle (und eigene Uploads) mit dem, was der Agent davon nutzt.

Der Chat-Agent sucht im Suchindex (state/suche.db, Volltext BM25) und in Chroma (state/chroma,
semantisch). Eine Datei ist eine Quelle, sobald sie im Volltext-Index steht. Die Aufbereitung
(Zusammenfassung, Folien) ist davon getrennt und läuft nur für Folien, Semesterprogramme und Projekte.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_agent.config import Settings
from study_agent.einstellungen import laden as laden_einstellungen, ueberspringen_grund
from study_agent.pipeline.ausschluss import laden as laden_ausschluss
from study_agent.pipeline.classify import ROUTES
from study_agent.pipeline.convert import CONVERTIBLE, COPYABLE, load_manifest
from study_agent.pipeline.eigene import EIGENE_DIR, eigene_files
from study_agent.pipeline.moodle_db import MoodleDbError, all_files
from study_agent.pipeline.pending import read_done
from study_agent.pipeline.suche import index_db_path

EIGENE_ABSCHNITT = "Eigene Dateien"
WEITERE_ABSCHNITT = "Weitere (nicht mehr in Moodle)"

ART = {
    "resource": "Datei", "folder": "Ordner", "url": "Link", "page": "Seite", "assign": "Abgabe",
    "forum": "Forum", "label": "Textfeld", "section_summary": "Abschnittstext",
    "url_description": "Linkbeschreibung", "choicegroup": "Gruppenwahl", "eigene": "Eigene Datei",
}
KLASSE = {
    "folien": "Folien", "uebung": "Übung", "loesung": "Lösung", "literatur": "Literatur",
    "semesterprogramm": "Semesterprogramm", "projekt": "Projekt", "unklar": "Klasse unklar",
    "ueberspringen": "Von Hand übersprungen",
}
# Status, was der Agent mit der Datei tut (Reihenfolge = Wichtigkeit in der Zusammenfassung)
NUTZT, BALD, SCAN, FEHLT, LINK, TYP, LEER, AUS = "nutzt", "bald", "scan", "fehlt", "link", "typ", "leer", "aus"
NICHT_GENUTZT = (FEHLT, LINK, TYP, LEER)


def _norm(s: str) -> str:
    return (s or "").translate(str.maketrans("⧸：｜？＜＞＂", "/:|?<>\"")).casefold().strip()


def _fts(state_dir: Path) -> tuple[dict[str, str], dict[str, int]]:
    """datei -> Quelle (folien|rohtext) und datei -> Anzahl Abschnitte aus dem Volltext-Index."""
    db = index_db_path(state_dir)
    if not db.exists():
        return {}, {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        quelle = dict(con.execute("SELECT datei, quelle FROM meta"))
        abschnitte = dict(con.execute("SELECT datei, COUNT(*) FROM suche GROUP BY datei"))
    except sqlite3.Error:
        return {}, {}
    finally:
        con.close()
    return quelle, abschnitte


def _chroma(state_dir: Path) -> dict[str, int]:
    """datei -> Anzahl eingebetteter Chunks, direkt aus Chromas SQLite (ohne Embedding-Modell)."""
    db = state_dir / "chroma" / "chroma.sqlite3"
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return dict(con.execute(
                "SELECT string_value, COUNT(*) FROM embedding_metadata WHERE key = 'datei' GROUP BY string_value"))
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def _iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _eintrag(rel: str, titel: str, art: str, pfad: Path, ctx: dict) -> dict[str, Any]:
    entry = ctx["manifest"].get(rel)
    quelle = ctx["fts"].get(rel)
    endung = pfad.suffix.lower()
    if rel in ctx["aus"]:
        status = AUS
    elif quelle:
        status = NUTZT if ctx["abschnitte"].get(rel) else LEER
    elif entry is not None:
        status = BALD
    elif art == "Link":
        status = LINK
    elif not pfad.exists():
        status = FEHLT
    elif endung == ".pdf":
        status = SCAN
    elif endung not in CONVERTIBLE | COPYABLE:
        status = TYP
    else:
        status = BALD

    aufbereitung, grund = None, None
    klasse = None
    if entry is not None:
        klasse = ctx["overrides"].get(rel, entry.get("klasse"))
        route = ROUTES.get(klasse)
        if route is None:
            aufbereitung = "nicht_noetig"
        elif ctx["done"].get(rel) == entry.get("sig"):
            aufbereitung = "fertig"
        else:
            grund = ueberspringen_grund(ctx["filt"], ctx["kurs"], pfad.name, pfad, route)
            aufbereitung = "uebersprungen" if grund else "offen"
    return {
        "rel": rel,
        "titel": titel,
        "art": art,
        "endung": endung.lstrip("."),
        "klasse": KLASSE.get(klasse or "", klasse),
        "status": status,
        "seiten": (entry or {}).get("seiten"),
        "abschnitte": ctx["abschnitte"].get(rel, 0),
        "folien_aufbereitet": quelle == "folien",
        "semantisch": ctx["chroma"].get(rel, 0),
        "texterkennung": bool((entry or {}).get("ocr")),
        "aufbereitung": aufbereitung,
        "grund": grund,
        "oeffnen": pfad.exists() and status != LINK,
        # Schritte für die Status-Tabelle: geladen → ausgelesen → zusammengefasst → Volltext → semantisch
        "geladen": pfad.exists(),
        "ausgelesen": entry is not None,
        "volltext": bool(quelle) and ctx["abschnitte"].get(rel, 0) > 0,
        "nutzen": rel not in ctx["aus"],
        "waehlbar": art != "Link",
    }


def quellen_modul(settings: Settings, kurs: str, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Alle Dateien eines Moduls nach Moodle-Abschnitt, mit Status für den Agenten und Zusammenfassung."""
    e = laden_einstellungen(settings.state_dir)
    fts, abschnitte = _fts(settings.state_dir)
    ctx = {
        "manifest": load_manifest(settings.knowledge_dir), "fts": fts, "abschnitte": abschnitte,
        "chroma": _chroma(settings.state_dir), "done": read_done(settings.state_dir),
        "overrides": overrides or {}, "kurs": kurs, "aus": laden_ausschluss(settings.state_dir),
        "filt": {**e["filter"], "archiv": e["semester"]["archiv"]},
    }
    ziel = _norm(kurs)
    gruppen: dict[str, list] = {}
    gesehen: set[str] = set()

    try:
        records = all_files(settings.moodle_db)
    except MoodleDbError:
        records = []
    for r in records:
        rel = r.rel(settings.data_dir)
        if rel is None or not rel.parts or _norm(rel.parts[0]) != ziel:
            continue
        key = rel.as_posix()
        if key in gesehen:
            continue
        gesehen.add(key)
        art = ART.get(r.module_type, r.module_type)
        titel = r.path.name if r.module_type == "resource" else (r.module_name or r.path.stem)
        if r.module_type == "section_summary":
            titel = "Beschreibung des Abschnitts"
        gruppen.setdefault(r.section or "Allgemein", []).append(_eintrag(key, titel, art, r.path, ctx))

    for f in eigene_files(settings.data_dir):
        if _norm(f.course) != ziel:
            continue
        rel = f.rel(settings.data_dir)
        if rel is None or rel.as_posix() in gesehen:
            continue
        gesehen.add(rel.as_posix())
        gruppen.setdefault(EIGENE_ABSCHNITT, []).append(
            _eintrag(rel.as_posix(), f.name, ART["eigene"], f.path, ctx))

    # Im Index, aber in Moodle nicht mehr vorhanden (alte Stände, gelöschte Dateien)
    for key in sorted(fts):
        teile = key.split("/")
        kurs_teil = teile[1] if teile[0] == EIGENE_DIR and len(teile) > 1 else teile[0]
        if key in gesehen or _norm(kurs_teil) != ziel:
            continue
        pfad = settings.data_dir / key
        gruppen.setdefault(WEITERE_ABSCHNITT, []).append(_eintrag(key, pfad.name, "Datei", pfad, ctx))

    alle = [d for ds in gruppen.values() for d in ds]
    zaehlen = lambda feld, wert: sum(1 for d in alle if d[feld] == wert)  # noqa: E731
    return {
        "kurs": kurs,
        "abschnitte": [{"name": n, "dateien": ds} for n, ds in gruppen.items()],
        "zusammenfassung": {
            "total": len(alle),
            "nutzt": zaehlen("status", NUTZT),
            "bald": zaehlen("status", BALD) + zaehlen("status", SCAN),
            "nicht": sum(1 for d in alle if d["status"] in NICHT_GENUTZT),
            "semantisch": sum(1 for d in alle if d["semantisch"]),
            "aufbereitet": zaehlen("aufbereitung", "fertig"),
            "aufbereitung_offen": zaehlen("aufbereitung", "offen"),
            "uebersprungen": zaehlen("aufbereitung", "uebersprungen"),
            "ausgeschlossen": zaehlen("status", AUS),
        },
        "stand": {
            "moodle": _iso(settings.moodle_db),
            "suchindex": _iso(index_db_path(settings.state_dir)),
        },
    }


VORSCHAU_ZEICHEN = 4000


def vorschau(settings: Settings, rel: str) -> dict[str, Any]:
    """Anfang des ausgelesenen Texts (Folien-Notizen, falls vorhanden). ValueError, wenn rel unbekannt ist."""
    import re

    from study_agent.pipeline.convert import folien_path, knowledge_path

    if rel not in load_manifest(settings.knowledge_dir):
        raise ValueError("Kein ausgelesener Text zu dieser Datei")
    folien = folien_path(settings.knowledge_dir, Path(rel))
    pfad = folien if folien.is_file() else knowledge_path(settings.knowledge_dir, Path(rel))
    if not pfad.is_file():
        raise ValueError("Kein ausgelesener Text zu dieser Datei")
    text = re.sub(r"<!--.*?-->", "", pfad.read_text(errors="replace"), flags=re.S).strip()
    return {"rel": rel, "text": text[:VORSCHAU_ZEICHEN], "gekuerzt": len(text) > VORSCHAU_ZEICHEN,
            "folien_notizen": pfad == folien}
