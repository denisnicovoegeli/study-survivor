"""Karteikarten-Routen und Begriffs-Parser fuer das Studium-Dashboard (T4).

Liest Begriffe aus lernen/<Kurs>/begriffe.md, fuehrt Duplikate zusammen,
extrahiert Folienverweise und verwaltet den Leitner-Lernstand in state/karten.json.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROW_RE = re.compile(r"^\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$")
_PAGE_RE = re.compile(r"Folie\s*(\d+)(?:\s*(?:-|bis|–)\s*(\d+))?", re.IGNORECASE)
_WEEK_RE = re.compile(r"(?:Woche|W)\s*0?(\d+)", re.IGNORECASE)


def parse_sources(quelle_str: str) -> List[Dict[str, Any]]:
    """Extrahiert Dateinamen und Foliennummern aus dem Quelle-Feld.

    Beispiel:
        "W03_training.pdf, Folie 45, 51; W04_Bilddaten.pdf, Folie 6-7"
    """
    if not quelle_str or not isinstance(quelle_str, str):
        return []

    sources = []
    # Teile an Semikolon
    parts = [p.strip() for p in quelle_str.split(";") if p.strip()]
    for part in parts:
        # Dateiname steht vor dem ersten Komma oder vor "Folie"
        # Dateinamen dürfen Leerzeichen enthalten («1 Generative AI.pdf»)
        pdf_match = re.search(r"([^,;|]+?\.(?:pdf|pptx|docx|md))\b", part, re.IGNORECASE)
        filename = pdf_match.group(1).strip() if pdf_match else ""

        # Foliennummern suchen
        pages = []
        for m in re.finditer(r"Folie\s+(\d+)(?:\s*(?:[-–]|bis)\s*(\d+))?", part, re.IGNORECASE):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            for p in range(start, min(start + 50, end + 1)):
                if p not in pages:
                    pages.append(p)

        # Auch einfache Kommazahlen hinter "Folie X, Y" erfassen
        after_folie = re.search(r"Folie\s+\d+(?:,\s*\d+)+", part, re.IGNORECASE)
        if after_folie:
            for num in re.findall(r"\b(\d+)\b", after_folie.group(0)):
                p = int(num)
                if p not in pages:
                    pages.append(p)

        sources.append({
            "raw": part,
            "filename": filename,
            "pages": sorted(pages),
        })

    return sources


def extract_weeks_from_sources(sources: List[Dict[str, Any]]) -> List[int]:
    """Ermittelt alle vorkommenden Wochennummern aus den Quelldateien."""
    weeks = set()
    for s in sources:
        raw_text = f"{s.get('filename', '')} {s.get('raw', '')}"
        m = _WEEK_RE.search(raw_text)
        if m:
            weeks.add(int(m.group(1)))
    return sorted(weeks)


def parse_begriffe_markdown(content: str) -> List[Dict[str, Any]]:
    """Liest die Begriffe-Tabelle aus Markdown und fuehrt Duplikate zusammen."""
    if not content or not isinstance(content, str):
        return []

    cards_by_key: Dict[str, Dict[str, Any]] = {}
    lines = content.splitlines()

    for line in lines:
        m = _ROW_RE.match(line)
        if not m:
            continue
        col1, col2, col3 = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()

        # Kopfzeile oder Trennzeile ueberspringen
        if col1.lower() == "begriff" or set(col1) <= {"-", ":", " "}:
            continue

        key = col1.lower()
        parsed_srcs = parse_sources(col3)

        if key in cards_by_key:
            # Duplikat zusammenfuehren
            existing = cards_by_key[key]
            # Definition ergaenzen, falls nicht bereits identisch
            if col2 and col2 not in existing["definitions"]:
                existing["definitions"].append(col2)
            if col3 and col3 not in existing["quellen"]:
                existing["quellen"].append(col3)
            # Quellen und Wochen zusammenfuehren
            for s in parsed_srcs:
                if not any(e["raw"] == s["raw"] for e in existing["sources"]):
                    existing["sources"].append(s)
            for w in extract_weeks_from_sources(parsed_srcs):
                if w not in existing["weeks"]:
                    existing["weeks"].append(w)
                    existing["weeks"].sort()
        else:
            cards_by_key[key] = {
                "id": col1,
                "begriff": col1,
                "definitions": [col2] if col2 else [],
                "quellen": [col3] if col3 else [],
                "sources": parsed_srcs,
                "weeks": extract_weeks_from_sources(parsed_srcs),
            }

    result = []
    for entry in cards_by_key.values():
        definition_text = "\n\n".join(entry["definitions"])
        quelle_text = "; ".join(entry["quellen"])
        result.append({
            "id": entry["id"],
            "begriff": entry["begriff"],
            "definition": definition_text,
            "quelle": quelle_text,
            "sources": entry["sources"],
            "weeks": entry["weeks"],
            "box": 1,
            "streak": 0,
            "reviewed_at": None,
        })

    return sorted(result, key=lambda c: c["begriff"].lower())


def get_karten_state_file(state_dir: Path) -> Path:
    return state_dir / "karten.json"


def load_karten_state(state_dir: Path) -> Dict[str, Any]:
    f = get_karten_state_file(state_dir)
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_karten_state(state_dir: Path, data: Dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = get_karten_state_file(state_dir)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def review_card(
    state_dir: Path, course: str, card_id: str, known: bool
) -> Dict[str, Any]:
    """Aktualisiert das Fach (Box 1-3) einer Karte nach dem Leitner-System."""
    state = load_karten_state(state_dir)
    course_state = state.setdefault(course, {})
    card_state = course_state.get(card_id, {"box": 1, "streak": 0, "reviewed_at": None})

    cur_box = card_state.get("box", 1)
    cur_streak = card_state.get("streak", 0)

    now_iso = datetime.now(timezone.utc).isoformat()

    if known:
        new_box = min(3, cur_box + 1)
        new_streak = cur_streak + 1
    else:
        new_box = 1
        new_streak = 0

    updated_card = {
        "box": new_box,
        "streak": new_streak,
        "reviewed_at": now_iso,
    }
    course_state[card_id] = updated_card
    save_karten_state(state_dir, state)

    return updated_card


def get_course_cards(
    course: str, lernen_dir: Path, state_dir: Path
) -> List[Dict[str, Any]]:
    """Laedt alle Karten des Kurses und versieht sie mit dem gespeicherten Leitner-Stand."""
    begriffe_file = lernen_dir / course / "begriffe.md"
    if not begriffe_file.is_file():
        # Fallback auf Gross-/Kleinschreibung des Kursordners
        for cdir in lernen_dir.iterdir() if lernen_dir.is_dir() else []:
            if cdir.name.lower() == course.lower():
                cand = cdir / "begriffe.md"
                if cand.is_file():
                    begriffe_file = cand
                    break

    if not begriffe_file.is_file():
        return []

    content = begriffe_file.read_text(encoding="utf-8", errors="replace")
    cards = parse_begriffe_markdown(content)

    state = load_karten_state(state_dir)
    course_state = state.get(course, {})

    for c in cards:
        cid = c["id"]
        if cid in course_state:
            c["box"] = course_state[cid].get("box", 1)
            c["streak"] = course_state[cid].get("streak", 0)
            c["reviewed_at"] = course_state[cid].get("reviewed_at")

    return cards


_job: Dict[str, Any] = {"status": "bereit"}
_job_lock = __import__("threading").Lock()


def register_routes(router: Any, get_settings_fn: Any) -> None:
    """Registriert Karteikarten-Routen am FastAPI-Router."""
    from fastapi import Body, Query

    @router.get("/karten")
    async def get_karten(course: str = Query(..., description="Name des Kurses")):
        settings = get_settings_fn()
        cards = get_course_cards(course, settings.lernen_dir, settings.state_dir)
        return {"course": course, "cards": cards, "total": len(cards)}

    @router.get("/karten/dokumente")
    def get_karten_dokumente(course: str = Query(...)):
        from study_agent.pipeline.karteikarten import dokumente
        return {"course": course, "dokumente": dokumente(get_settings_fn(), course), "job": dict(_job)}

    @router.post("/karten/erstellen")
    def post_karten_erstellen(payload: Dict[str, Any] = Body(...)):
        """Startet die Erstellung im Hintergrund; Status per GET /karten/erstellen."""
        import threading

        from fastapi import HTTPException

        from study_agent.pipeline.karteikarten import erstellen

        course = str(payload.get("course") or "")
        rels = [str(r) for r in payload.get("rels") or []][:40]
        if not course or not rels:
            raise HTTPException(400, "course und rels fehlen")
        with _job_lock:
            if _job.get("status") == "läuft":
                raise HTTPException(409, "Es werden schon Karteikarten erstellt.")
            _job.clear()
            _job.update(status="läuft", course=course, total=len(rels), index=0, datei="", neu=0, fehler=[])
        settings = get_settings_fn()

        def fortschritt(i, datei):
            _job.update(index=i, datei=datei)

        def run():
            try:
                r = erstellen(settings, course, rels, int(payload.get("anzahl") or 10), fortschritt=fortschritt)
                _job.update(status="fertig", index=len(rels), datei="", **r)
            except Exception as exc:  # noqa: BLE001
                _job.update(status="fehler", fehler=[f"{type(exc).__name__}: {exc}"])

        threading.Thread(target=run, daemon=True).start()
        return dict(_job)

    @router.get("/karten/erstellen")
    def get_karten_erstellen():
        return dict(_job)

    @router.post("/karten/review")
    async def post_karten_review(payload: Dict[str, Any] = Body(...)):
        course = str(payload.get("course") or "")
        card_id = str(payload.get("card_id") or "")
        known = bool(payload.get("known", False))

        settings = get_settings_fn()
        updated = review_card(settings.state_dir, course, card_id, known)
        return {"ok": True, "card": updated}
