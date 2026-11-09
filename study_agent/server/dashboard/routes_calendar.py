"""Kalender-Routen, Zusammenfuehrung und YAML-Bearbeitung (T5).

Regeln:
- Schweizer Rechtschreibung (ss statt sz, keine Geviertstriche).
- Eigene Termine in termine/<Kurs>.yaml schreiben; Kommentare und Feld geprueft bleiben erhalten.
- Moodle-Termine nur lesbar, aber ausblendbar.
- Duplikate (gleicher Kurs, gleicher Tag, gleiche Art, aehnlicher Titel) werden zusammengefuehrt:
  Uhrzeit aus Moodle, Quelle "Moodle + Semesterprogramm".
- Deep-Learning-Projektabgabe erscheint nur noch einmal.
"""

import difflib
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    import yaml  # Projekt-venv (Tests, CLI)
    _safe_load = yaml.safe_load
except ImportError:  # Hermes-venv hat nur ruamel.yaml
    from ruamel.yaml import YAML as _YAML

    def _safe_load(text):
        return _YAML(typ="safe", pure=True).load(text)

# Von plugin_api gesetzt: Hermes laedt das Plugin ohne Paket, ein Import von
# dashboard.plugin_api wuerde dort eine zweite Kopie erzeugen.
project_dir_fn = None

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    APIRouter = None
    class HTTPException(Exception):
        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    class BaseModel:
        def dict(self):
            return self.__dict__

TZ = ZoneInfo("Europe/Zurich")
_FULLWIDTH = str.maketrans("⧸：｜？＜＞＂", "/:|?<>\"")

KINDS = frozenset({"abgabe", "pruefung", "praesentation", "meilenstein", "praesenz", "ausfall", "lektion", "termin"})


# ---------------------------------------------------------------------------
# Hilfsfunktionen fuer Normalisierung und Aehnlichkeit
# ---------------------------------------------------------------------------

def normalize_course(course: str) -> str:
    """Bereinigt Kursnamen fuer Vergleiche (Vollbreitenzeichen, Kleinbuchstaben)."""
    return (course or "").translate(_FULLWIDTH).casefold().strip()


def normalize_kind(kind: str) -> str:
    """Normalisiert Termin- und Moodle-Arten."""
    k = (kind or "").strip().lower()
    if k in ("assign", "assignment", "assignments", "abgabe"):
        return "abgabe"
    if k in ("quiz", "exam", "test", "pruefung", "prüfung"):
        return "pruefung"
    if k in ("praesentation", "präsentation", "presentation"):
        return "praesentation"
    return k


def parse_due_date(due_val: Any) -> Optional[date]:
    """Wandelt due-Wert (ISO-String oder datetime) in das Datum gemaess Zuercher Zeit um."""
    if not due_val:
        return None
    if isinstance(due_val, datetime):
        return due_val.astimezone(TZ).date()
    if isinstance(due_val, date):
        return due_val
    raw = str(due_val).strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).date()
    except Exception:
        # Fallback falls reines Datumsformat "YYYY-MM-DD"
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def similar_title(t1: str, t2: str) -> bool:
    """Prueft, ob zwei Termintitel aehnlich sind (gleiche Sache beschreiben)."""
    s1 = re.sub(r"[^\w\s]", " ", (t1 or "").lower())
    s2 = re.sub(r"[^\w\s]", " ", (t2 or "").lower())
    w1 = set(s1.split())
    w2 = set(s2.split())
    if not w1 or not w2:
        return False

    # Exakte Gleichheit oder Teilstring
    if s1.strip() == s2.strip() or s1 in s2 or s2 in s1:
        return True

    overlap = w1 & w2
    if overlap:
        # Wichtige Kernbegriffe
        key_terms = {
            "projekt", "abgabe", "bericht", "upload", "dokumentation",
            "präsentation", "praesentation", "prüfung", "pruefung", "exam",
            "review", "retro", "meilenstein"
        }
        if overlap & key_terms:
            return True
        if len(overlap) / max(len(w1), len(w2)) >= 0.3:
            return True

    # Differenz-Aehnlichkeit
    if difflib.SequenceMatcher(None, s1, s2).ratio() >= 0.5:
        return True

    return False


# ---------------------------------------------------------------------------
# Zusammenfuehren von Moodle-Deadlines und lokalen Terminen
# ---------------------------------------------------------------------------

def merge_calendar_events(deadlines: List[Dict[str, Any]], termine: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fuehrt Moodle-Deadlines und termine/*.yaml zusammen.

    Gleicher Kurs, gleicher Tag, gleiche Art und aehnlicher Titel ergeben einen
    zusammengefuehrten Eintrag mit Uhrzeit aus Moodle und Quelle 'Moodle + Semesterprogramm'.
    Fuer die Art 'abgabe' werden Termine am gleichen Kurs und Tag auch bei unaehnlichem
    Titel zusammengefuehrt.
    """
    merged: List[Dict[str, Any]] = []
    used_termin_indices = set()

    for d in deadlines:
        d_item = dict(d)
        d_course = normalize_course(d_item.get("course", ""))
        d_cid = int(d_item.get("course_id") or 0)
        d_day = parse_due_date(d_item.get("due") or d_item.get("datum"))
        d_kind = normalize_kind(d_item.get("kind") or d_item.get("art") or "")
        d_title = str(d_item.get("name") or d_item.get("titel") or "")

        matched_idx: Optional[int] = None
        for idx, t in enumerate(termine):
            if idx in used_termin_indices:
                continue
            t_cid = int(t.get("course_id") or 0)
            t_course = normalize_course(t.get("course", ""))

            # 1. Kurspruefung
            course_match = (d_cid and t_cid and d_cid == t_cid) or (d_course and t_course and d_course == t_course)
            if not course_match:
                continue

            # 2. Tagpruefung (in Zuercher Zeit)
            t_day = parse_due_date(t.get("due") or t.get("datum"))
            if not d_day or not t_day or d_day != t_day:
                continue

            # 3. Artpruefung
            t_kind = normalize_kind(t.get("kind") or t.get("art") or "")
            kind_match = (d_kind == t_kind) or (not d_kind or not t_kind)
            if not kind_match:
                continue

            # 4. Titel-Aehnlichkeit bzw. Abgabe-Zusammenfuehrung
            t_title = str(t.get("name") or t.get("titel") or "")
            if similar_title(d_title, t_title):
                matched_idx = idx
                break
            elif d_kind == "abgabe" and t_kind == "abgabe" and matched_idx is None:
                # Bei gleichem Kurs, gleichem Tag und Art abgabe auch bei unaehnlichem Titel zusammenfuehren
                matched_idx = idx

        if matched_idx is not None:
            # Duplikat gefunden: Zusammenfuehren
            used_termin_indices.add(matched_idx)
            t_match = termine[matched_idx]

            merged_event = dict(t_match)
            # Uhrzeit aus Moodle uebernehmen
            merged_event["due"] = d_item.get("due") or t_match.get("due")
            merged_event["all_day"] = False
            merged_event["source"] = "Moodle + Semesterprogramm"
            merged_event["quelle"] = "moodle+termin"
            merged_event["url"] = d_item.get("url") or t_match.get("url") or ""
            merged_event["course"] = d_item.get("course") or t_match.get("course")
            merged_event["course_id"] = d_cid or int(t_match.get("course_id") or 0)
            merged_event["is_moodle"] = True
            merged_event["is_termin"] = True
            merged_event["editable"] = True
            t_match_kind = normalize_kind(t_match.get("kind") or t_match.get("art") or "")
            merged_event["kind"] = "abgabe" if (d_kind == "abgabe" or t_match_kind == "abgabe") else (d_kind or t_match_kind)
            # Den aussagekraeftigeren Titel waehlen
            t_name = str(t_match.get("name") or t_match.get("titel") or "")
            # Titel aus der Termin-Datei merken: Aendern und Loeschen suchen danach,
            # auch wenn der angezeigte Name aus Moodle stammt (A3 fuehrt unaehnliche Titel zusammen)
            merged_event["termin_titel"] = t_name
            if len(t_name) >= len(d_title):
                merged_event["name"] = t_name
            else:
                merged_event["name"] = d_title

            merged.append(merged_event)
        else:
            # Reiner Moodle-Termin (nur lesbar)
            d_item["quelle"] = "moodle"
            d_item["source"] = d_item.get("source") or "Moodle"
            d_item["is_moodle"] = True
            d_item["is_termin"] = False
            d_item["editable"] = False
            d_item["kind"] = d_kind
            merged.append(d_item)

    # Verbleibende Termine anhaengen
    for idx, t in enumerate(termine):
        if idx not in used_termin_indices:
            t_item = dict(t)
            t_item["quelle"] = "termin"
            t_item["source"] = t_item.get("source") or "Semesterprogramm"
            t_item["is_moodle"] = False
            t_item["is_termin"] = True
            t_item["editable"] = True
            if "kind" not in t_item and "art" in t_item:
                t_item["kind"] = normalize_kind(t_item["art"])
            merged.append(t_item)

    merged.sort(key=lambda e: str(e.get("due", "")))
    return merged


# ---------------------------------------------------------------------------
# YAML-Manipulation mit Erhalt von Kommentaren und geprueft
# ---------------------------------------------------------------------------

def _get_project_dir() -> Path:
    if project_dir_fn is not None:
        return project_dir_fn()
    from study_agent.server.dashboard.plugin_api import project_dir
    return project_dir()


def _get_termine_dir(custom_dir: Optional[Path] = None) -> Path:
    if custom_dir is not None:
        return custom_dir
    return _get_project_dir() / "termine"


def find_termin_file(course: str, termine_dir: Path) -> Path:
    """Findet die passende YAML-Datei im termine/-Verzeichnis oder erzeugt den Zielpfad."""
    norm = normalize_course(course)
    for p in sorted(termine_dir.glob("*.yaml")):
        try:
            content = _safe_load(p.read_text(encoding="utf-8")) or {}
            if normalize_course(str(content.get("kurs") or "")) == norm:
                return p
        except Exception:
            continue

    # Fallback: Dateiname nach Kurs
    clean_name = course.replace("/", "⧸").strip()
    return termine_dir / f"{clean_name}.yaml"


def _format_entry(datum: str, titel: str, art: str, zeit: Optional[str] = None, quelle: Optional[str] = None) -> List[str]:
    """Erzeugt formatierte YAML-Zeilen fuer einen Termin-Eintrag."""
    lines = [f"  - datum: {datum}"]
    if zeit:
        lines.append(f'    zeit: "{zeit}"')
    # Titel sauber quotieren
    safe_titel = titel.replace('"', '\\"')
    lines.append(f'    titel: "{safe_titel}"')
    lines.append(f"    art: {art}")
    if quelle:
        safe_quelle = quelle.replace('"', '\\"')
        lines.append(f'    quelle: "{safe_quelle}"')
    return lines


def _split_into_blocks(lines: List[str]) -> Tuple[List[str], List[Tuple[Dict[str, Any], int, int]]]:
    """Zerlegt den termine:-Bereich in einzelne Bloecke pro Listeneintrag.

    Gibt (header_lines, blocks) zurueck, wobei jeder Block:
    (parsed_dict, start_line_idx, end_line_idx) enthaelt.
    """
    in_termine = False
    termine_line_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*termine\s*:\s*(#.*)?$", line):
            in_termine = True
            termine_line_idx = i
            break

    if not in_termine:
        return lines, []

    blocks = []
    current_start = -1
    current_lines = []

    def flush_block(end_idx: int):
        nonlocal current_start, current_lines
        if current_start != -1 and current_lines:
            text = "\n".join(current_lines)
            # Fuehrendes "  - " durch "- " ersetzen fuer YAML-Parsing
            try:
                parsed_list = _safe_load(text)
                if isinstance(parsed_list, list) and len(parsed_list) > 0:
                    blocks.append((parsed_list[0], current_start, end_idx))
            except Exception:
                pass
        current_start = -1
        current_lines = []

    for i in range(termine_line_idx + 1, len(lines)):
        line = lines[i]
        # Neuer Listeneintrag beginnt mit '  - ' oder '- '
        if re.match(r"^\s*-\s+", line):
            flush_block(i)
            current_start = i
            current_lines = [line]
        elif current_start != -1:
            # Gehoert zum aktuellen Block, falls eingerueckt
            if re.match(r"^\s{2,}", line) or line.strip() == "" or line.strip().startswith("#"):
                current_lines.append(line)
            else:
                # Nicht mehr eingerueckt -> Ende der termine-Sektion
                flush_block(i)
                break

    flush_block(len(lines))
    return lines[:termine_line_idx + 1], blocks


def add_termin(course: str, data: Dict[str, Any], termine_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Fuegt einen Termin zur entsprechenden termine/<Kurs>.yaml hinzu."""
    tdir = _get_termine_dir(termine_dir)
    tdir.mkdir(parents=True, exist_ok=True)
    path = find_termin_file(course, tdir)

    datum = str(data.get("datum") or "").strip()
    titel = str(data.get("titel") or "").strip()
    art = str(data.get("art") or "termin").strip()
    zeit = data.get("zeit")
    if zeit is not None:
        zeit = str(zeit).strip()
    quelle = data.get("quelle")
    if quelle is not None:
        quelle = str(quelle).strip()

    if not datum or not re.match(r"^\d{4}-\d{2}-\d{2}$", datum):
        raise ValueError(f"Ungueltiges Datum: {datum!r}")
    if not titel:
        raise ValueError("Titel darf nicht leer sein.")
    if art not in KINDS:
        raise ValueError(f"Ungueltige Art: {art!r}, erlaubt: {', '.join(sorted(KINDS))}")

    new_lines = _format_entry(datum, titel, art, zeit, quelle)

    if not path.exists():
        # Neue Datei anlegen
        header = [
            f'kurs: "{course}"',
            f"geprueft: {date.today().isoformat()}",
            "termine:",
        ]
        full_text = "\n".join(header + new_lines) + "\n"
        path.write_text(full_text, encoding="utf-8")
        return {"ok": True, "path": str(path)}

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Pruefen, ob 'termine:' vorhanden ist
    termine_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*termine\s*:\s*(#.*)?$", line):
            termine_idx = i
            break

    if termine_idx == -1:
        # termine: anhaengen
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append("termine:")
        lines.extend(new_lines)
    else:
        # An das Ende der termine-Sektion anhaengen
        last_item_idx = termine_idx
        for i in range(termine_idx + 1, len(lines)):
            line = lines[i]
            if re.match(r"^\s*-\s+", line) or re.match(r"^\s{2,}", line) or line.strip() == "" or line.strip().startswith("#"):
                last_item_idx = i
            else:
                break
        lines = lines[:last_item_idx + 1] + new_lines + lines[last_item_idx + 1:]

    new_content = "\n".join(lines) + "\n"
    # Validierung: Kann PyYAML es fehlerfrei parsen?
    _safe_load(new_content)
    path.write_text(new_content, encoding="utf-8")

    return {"ok": True, "path": str(path)}


def update_termin(course: str, original: Dict[str, Any], updated: Dict[str, Any], termine_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Aktualisiert einen bestehenden Termin und behaelt Kommentare und geprueft bei."""
    tdir = _get_termine_dir(termine_dir)
    path = find_termin_file(course, tdir)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Termin-Datei fuer diesen Kurs nicht gefunden.")

    orig_datum = str(original.get("datum") or "").strip()
    orig_titel = str(original.get("titel") or "").strip()

    new_datum = str(updated.get("datum") or orig_datum).strip()
    new_titel = str(updated.get("titel") or orig_titel).strip()
    new_art = str(updated.get("art") or original.get("art") or "termin").strip()
    new_zeit = updated.get("zeit", original.get("zeit"))
    if new_zeit is not None:
        new_zeit = str(new_zeit).strip()
    new_quelle = updated.get("quelle", original.get("quelle"))
    if new_quelle is not None:
        new_quelle = str(new_quelle).strip()

    if not new_datum or not re.match(r"^\d{4}-\d{2}-\d{2}$", new_datum):
        raise ValueError(f"Ungueltiges Datum: {new_datum!r}")
    if not new_titel:
        raise ValueError("Titel darf nicht leer sein.")
    if new_art not in KINDS:
        raise ValueError(f"Ungueltige Art: {new_art!r}")

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    _, blocks = _split_into_blocks(lines)
    target_block = None

    for block_data, start_idx, end_idx in blocks:
        b_datum = str(block_data.get("datum") or "")
        b_titel = str(block_data.get("titel") or "")
        if b_datum == orig_datum and b_titel == orig_titel:
            target_block = (start_idx, end_idx)
            break

    # Falls kein exakter Match, versuche Aehnlichkeit
    if not target_block:
        for block_data, start_idx, end_idx in blocks:
            b_datum = str(block_data.get("datum") or "")
            b_titel = str(block_data.get("titel") or "")
            if b_datum == orig_datum and similar_title(b_titel, orig_titel):
                target_block = (start_idx, end_idx)
                break

    if not target_block:
        raise HTTPException(status_code=404, detail="Zu aktualisierender Termin nicht in der Datei gefunden.")

    start_idx, end_idx = target_block
    replacement = _format_entry(new_datum, new_titel, new_art, new_zeit, new_quelle)

    new_lines = lines[:start_idx] + replacement + lines[end_idx:]
    new_content = "\n".join(new_lines) + "\n"

    _safe_load(new_content)
    path.write_text(new_content, encoding="utf-8")

    return {"ok": True, "path": str(path)}


def delete_termin(course: str, target: Dict[str, Any], termine_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Loescht einen Termin aus der Datei und behaelt alle anderen Inhalte bei."""
    tdir = _get_termine_dir(termine_dir)
    path = find_termin_file(course, tdir)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Termin-Datei fuer diesen Kurs nicht gefunden.")

    t_datum = str(target.get("datum") or "").strip()
    t_titel = str(target.get("titel") or "").strip()

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    _, blocks = _split_into_blocks(lines)
    target_block = None

    for block_data, start_idx, end_idx in blocks:
        b_datum = str(block_data.get("datum") or "")
        b_titel = str(block_data.get("titel") or "")
        if b_datum == t_datum and (b_titel == t_titel or similar_title(b_titel, t_titel)):
            target_block = (start_idx, end_idx)
            break

    if not target_block:
        raise HTTPException(status_code=404, detail="Termin nicht in der Datei gefunden.")

    start_idx, end_idx = target_block
    new_lines = lines[:start_idx] + lines[end_idx:]
    new_content = "\n".join(new_lines) + "\n"

    _safe_load(new_content)
    path.write_text(new_content, encoding="utf-8")

    return {"ok": True}


# ---------------------------------------------------------------------------
# API Schemas und Endpoints
# ---------------------------------------------------------------------------

if HAS_FASTAPI:
    router = APIRouter(prefix="/calendar", tags=["calendar"])

    class TerminCreateRequest(BaseModel):
        course: str
        datum: str
        titel: str
        art: str = "termin"
        zeit: Optional[str] = None
        quelle: Optional[str] = None


    class TerminUpdateRequest(BaseModel):
        course: str
        original: Dict[str, Any]
        updated: Dict[str, Any]


    class TerminDeleteRequest(BaseModel):
        course: str
        datum: str
        titel: str


    @router.post("/events")
    def post_event(req: TerminCreateRequest):
        try:
            return add_termin(req.course, req.dict())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


    @router.put("/events")
    def put_event(req: TerminUpdateRequest):
        try:
            return update_termin(req.course, req.original, req.updated)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


    @router.delete("/events")
    def delete_event(req: TerminDeleteRequest):
        try:
            return delete_termin(req.course, {"datum": req.datum, "titel": req.titel})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
else:
    router = None
