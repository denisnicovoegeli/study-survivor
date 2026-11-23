"""Modulübersicht-Route für das Studium-Dashboard (T8).

Liefert strukturierte Modul-Informationen für einen Kurs:
- Leistungsnachweis (Art, Gewichtung, Dauer, Hilfsmittel, Termine, Quellen)
- Anstehende Termine nur dieses Moduls (gefiltert aus calendar_events)
- Fortschritt pro Woche (verarbeitet vs. offen aus study pending --json und Artefakten)
- Prüfungs- und Projektdetails (mit Quellenverweis)
- Noten des Moduls aus study grades --json
- Hinweis "Modulinfos noch nicht erzeugt", falls modul.md fehlt
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_FULLWIDTH = str.maketrans("⧸：｜？＜＞＂", "/:|?<>\"")
_WEEK_RE = re.compile(r"(?:Woche|W)\s*0?(\d+)", re.IGNORECASE)

# Von plugin_api injizierbar
project_dir_fn: Optional[Callable[[], Path]] = None
data_dir_fn: Optional[Callable[[], Path]] = None
cached_study_fn: Optional[Callable[..., Any]] = None
calendar_events_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None


def normalize_course(course: str) -> str:
    return (course or "").translate(_FULLWIDTH).casefold().strip()


def extract_week_num(text: str) -> Optional[int]:
    m = _WEEK_RE.search(text or "")
    return int(m.group(1)) if m else None


WICHTIGE_ARTEN = ("pruefung", "abgabe", "praesentation")


def _zuerich_datum(due: Any) -> Optional[str]:
    """ISO-Datum in Zürcher Zeit. Ganztägige Termine liegen als 22:59 UTC vor (= 23:59 des Tages)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    text = str(due or "").strip()
    if not text:
        return None
    try:
        d = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None
    if d.tzinfo is not None:
        d = d.astimezone(ZoneInfo("Europe/Zurich"))
    return d.date().isoformat()


def wichtige_daten(modul_daten: List[str], termine: List[Dict[str, Any]], heute: str) -> List[Dict[str, Any]]:
    """Daten zum Leistungsnachweis: Prüfung, Abgaben, Präsentationen.

    modul.md sammelt beim Zusammenfassen oft alle Unterrichtsdaten aus dem Semesterprogramm.
    Einträge ohne Beschreibung sind solche Lektionen und fallen weg; dazu kommen die Termine
    der Arten Prüfung, Abgabe und Präsentation aus dem Kalender.
    """
    from difflib import SequenceMatcher

    from study_agent.pipeline.modul import _datum_eintrag, _vergleichstext

    out: List[Dict[str, Any]] = []

    def add(iso: Optional[str], text: str, art: str, quelle: str = "") -> None:
        text = text.strip().rstrip(":").strip()
        if not iso or not text:
            return
        key = _vergleichstext(text)
        for e in out:
            if e["datum"] == iso:
                vkey = _vergleichstext(e["text"])
                if key == vkey or key.startswith(vkey) or vkey.startswith(key) \
                        or SequenceMatcher(None, key, vkey).ratio() > 0.85:
                    if len(text) > len(e["text"]):
                        e["text"] = text
                    return
        out.append({"datum": iso, "text": text, "art": art, "quelle": quelle, "vergangen": iso < heute})

    for ev in termine:
        if ev.get("kind") in WICHTIGE_ARTEN:
            add(_zuerich_datum(ev.get("due") or ev.get("date")), str(ev.get("name") or ""), ev["kind"],
                str(ev.get("source") or ""))
    for eintrag in modul_daten:
        iso, rest = _datum_eintrag(str(eintrag))
        add(iso, rest, "modul")
    return sorted(out, key=lambda e: e["datum"])


def get_modul_data(
    course: str,
    project_dir: Path,
    cached_study: Optional[Callable[..., Any]] = None,
    calendar_events: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Sammelt alle Daten für die Modulübersicht eines Kurses."""
    from study_agent.pipeline.modul import load_modul

    norm_course = normalize_course(course)
    lernen_dir = project_dir / "lernen"
    course_dir = lernen_dir / course

    # Fallback für Gross-/Kleinschreibung des Ordnernamens
    if not course_dir.is_dir() and lernen_dir.is_dir():
        for d in lernen_dir.iterdir():
            if d.is_dir() and normalize_course(d.name) == norm_course:
                course_dir = d
                break

    modul_info = load_modul(course_dir)
    hinweis = None if modul_info.has_modul_file else "Modulinfos noch nicht erzeugt"

    # 1. Anstehende Termine filtern
    events: List[Dict[str, Any]] = []
    if calendar_events is not None:
        try:
            all_events = calendar_events(days=120) or []
            today_str = str(date.today())
            for ev in all_events:
                ev_course = ev.get("course") or ""
                if normalize_course(ev_course) == norm_course:
                    ev_date = str(ev.get("date") or ev.get("datum") or "")
                    if not ev_date or ev_date >= today_str:
                        events.append(ev)
            events.sort(key=lambda x: str(x.get("date") or x.get("datum") or ""))
        except Exception:
            events = []

    # 2. Noten holen
    noten: Optional[Dict[str, Any]] = None
    if cached_study is not None:
        try:
            grades_data = cached_study("grades", "--json")
            if isinstance(grades_data, list):
                for g in grades_data:
                    if isinstance(g, dict):
                        g_course = g.get("course") or ""
                        if normalize_course(g_course) == norm_course or norm_course in normalize_course(g_course):
                            noten = {
                                "grade": g.get("grade"),
                                "raw_grade": g.get("raw_grade"),
                                "rank": g.get("rank"),
                            }
                            break
        except Exception:
            noten = None

    # 3. Fortschritt pro Woche aus pending --json und Artefakten
    pending_items: List[Dict[str, Any]] = []
    if cached_study is not None:
        try:
            p_data = cached_study("pending", "--json")
            if isinstance(p_data, list):
                pending_items = [
                    p for p in p_data
                    if isinstance(p, dict) and normalize_course(p.get("course") or "") == norm_course
                ]
        except Exception:
            pending_items = []

    # Offene Dateien nach Abschnitt/Woche gruppieren
    open_by_section: Dict[str, int] = {}
    for p in pending_items:
        sec = p.get("section") or "Allgemein"
        open_by_section[sec] = open_by_section.get(sec, 0) + 1

    # Verarbeitete Dateien (Zusammenfassungen / Folien) im Kurs-Lernordner zählen
    done_by_section: Dict[str, int] = {}
    if course_dir.is_dir():
        for item in course_dir.iterdir():
            if item.is_dir():
                sec_name = item.name
                zfs = list(item.glob("*.zusammenfassung.md"))
                folien = list(item.glob("*.folien.md"))
                count = max(len(zfs), len(folien))
                done_by_section[sec_name] = count

    all_sections = sorted(
        set(list(open_by_section.keys()) + list(done_by_section.keys())),
        key=lambda s: (extract_week_num(s) is None, extract_week_num(s) or 0, s.lower())
    )

    fortschritt: List[Dict[str, Any]] = []
    total_verarbeitet = 0
    total_offen = 0

    for sec in all_sections:
        ver = done_by_section.get(sec, 0)
        off = open_by_section.get(sec, 0)
        tot = ver + off
        pct = round(100 * ver / tot) if tot > 0 else 100
        w_num = extract_week_num(sec)
        w_label = f"Woche {w_num}" if w_num is not None else sec
        fortschritt.append({
            "section": sec,
            "week_label": w_label,
            "week_num": w_num,
            "verarbeitet": ver,
            "offen": off,
            "total": tot,
            "prozent": pct,
        })
        total_verarbeitet += ver
        total_offen += off

    return {
        "course": course,
        "has_modul_file": modul_info.has_modul_file,
        "hinweis": hinweis,
        "leistungsnachweis": {
            "art": modul_info.leistungsnachweis,
            "gewichtung": modul_info.gewichtung,
            "dauer": modul_info.dauer,
            "hilfsmittel": modul_info.hilfsmittel,
            "daten": modul_info.daten,
            "quellen": modul_info.quellen,
        },
        "termine": events,
        "wichtige_daten": wichtige_daten(modul_info.daten, events, str(date.today())),
        "fortschritt": {
            "wochen": fortschritt,
            "gesamt": {
                "verarbeitet": total_verarbeitet,
                "offen": total_offen,
                "total": total_verarbeitet + total_offen,
                "prozent": round(100 * total_verarbeitet / (total_verarbeitet + total_offen)) if (total_verarbeitet + total_offen) > 0 else 100,
            },
        },
        "noten": noten,
        "pruefung": modul_info.pruefung_items,
        "projekt": modul_info.projekt_items,
        "legacy_pruefung": modul_info.legacy_pruefung_text,
        "legacy_projekt": modul_info.legacy_projekt_text,
    }


def register_routes(
    router: Any,
    get_settings_fn: Any,
    cached_study: Any,
    calendar_events: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> None:
    """Registriert die Modul-Routen am FastAPI-Router."""
    from fastapi import HTTPException

    @router.get("/kurs/{course}/modul")
    def get_kurs_modul(course: str):
        settings = get_settings_fn()
        proj_dir = settings.project_dir
        cs_fn = cached_study_fn or cached_study
        ce_fn = calendar_events_fn or calendar_events
        try:
            return get_modul_data(
                course=course,
                project_dir=proj_dir,
                cached_study=cs_fn,
                calendar_events=ce_fn,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Fehler beim Laden der Moduldaten: {exc}")
