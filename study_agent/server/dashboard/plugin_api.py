"""Studium dashboard plugin backend, mounted at /api/plugins/studium/.

Lern-Cockpit für den Study Agent. Liest ausschliesslich über die study-CLI
(``study ... --json``) und Dateien unter ``lernen/``. Geschrieben werden der
Kanban-Zustand (``state/studium-kanban.json``) sowie im Lern-Workspace
``lernen/**/*.md`` und ``knowledge/**/*.folien.md`` (mit Kopie unter
``state/versionen/``); Moodle und die Kursdateien werden nie verändert.

Der FastAPI-``router`` wird nur gebaut, wenn fastapi verfügbar ist (im
Dashboard-Prozess). Damit lässt sich das Modul in der Projekt-``.venv`` (ohne
fastapi) importieren und testen.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")

# Spalten des Lern-Kanban (Auftragsbrett), in Reihenfolge.
COLUMNS = ("vorschlaege", "freigegeben", "in_arbeit", "pruefen", "erledigt")

# Deployment-Pfade (dokumentiert in docs/hermes-goal.md; per Umgebungsvariable
# übersteuerbar). Keine Zugangsdaten.
_DATA_DIR_DEFAULT = "/opt/data/moodle"

_KANBAN_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

def project_dir() -> Path:
    """Datenordner (data/): knowledge, lernen, termine, state."""
    from study_agent.config import load_settings
    return load_settings().project_dir


def data_dir() -> Path:
    """Kursdateien von moodle-dl (STUDY_DATA_DIR, Standard ~/Apps/moodle-dl)."""
    from study_agent.config import load_settings
    return load_settings().data_dir


def _plugin_imports() -> None:
    """Früher Suchpfad für das Hermes-Plugin, jetzt ein normales Paket."""


def get_settings():
    _plugin_imports()
    from study_agent.config import Settings
    return Settings(data_dir=data_dir(), project_dir=project_dir())


def study_bin() -> Path:
    from study_agent.config import REPO_DIR
    return REPO_DIR / ".venv" / "bin" / "study"


# ---------------------------------------------------------------------------
# study-CLI
# ---------------------------------------------------------------------------

def run_study(*args: str, timeout: int = 90) -> list:
    """Führt ``study <args> --json`` aus und liefert die geparste JSON-Liste.

    Liefert ``[]`` bei fehlendem Binary, Timeout, nicht-JSON oder nicht-Liste.
    Ein Exit-Code ungleich 0 ist kein Ausschlusskriterium: ``study termine``
    beendet sich mit 1, wenn eine YAML-Datei einen Fehler enthält, liefert aber
    die gültigen Termine trotzdem auf stdout.
    """
    proc = _run_study_proc(*args, timeout=timeout)
    if proc is None:
        return []
    out = (proc.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _run_study_proc(*args: str, timeout: int = 90):
    """Führt ``study <args>`` als Subprozess aus und liefert das CompletedProcess (oder None)."""
    bin_path = study_bin()
    if not bin_path.exists():
        return None
    env = os.environ.copy()
    env["STUDY_DATA_DIR"] = str(data_dir())
    env["STUDY_PROJECT_DIR"] = str(project_dir())
    # Der Hermes-Container setzt PYTHONDONTWRITEBYTECODE=1. Ohne Bytecode-Cache
    # kompiliert jeder study-Aufruf alle Module neu (Pi 4: ~3,1 s nur fuer den
    # Import). Mit Cache unter state/pycache (gitignored) sind es ~0,75 s.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.setdefault("PYTHONPYCACHEPREFIX", str(project_dir() / "state" / "pycache"))
    try:
        return subprocess.run(
            [str(bin_path), *args], capture_output=True, text=True,
            timeout=timeout, cwd=str(study_bin().parents[2]), env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None


# ---------------------------------------------------------------------------
# Zwischenspeicher für study-Aufrufe und teure Dateiarbeit
# ---------------------------------------------------------------------------
# Ergebnisse werden pro Schlüssel gemerkt: jung direkt aus dem Speicher, älter
# sofort aus dem Speicher und im Hintergrund neu geholt. Erst nach
# CACHE_MAX_AGE_S wird gewartet. Ändert sich die Signatur der Quelldateien
# (mtime), wird sofort neu geholt. Gleichzeitige Anfragen für denselben
# Schlüssel warten auf einen einzigen Lauf.

CACHE_FRESH_S = 60
CACHE_MAX_AGE_S = 30 * 60

_cache: dict = {}  # key -> (zeitpunkt, daten, signatur)
_cache_lock = threading.Lock()
_key_locks: dict = {}
_refreshing: set = set()


def _mtimes(*paths: Path) -> tuple:
    """Signatur aus mtime_ns der Pfade; bei Ordnern auch der direkten Einträge."""
    sig = []
    for p in paths:
        try:
            sig.append((str(p), p.stat().st_mtime_ns))
            if p.is_dir():
                sig.extend((e.name, e.stat().st_mtime_ns) for e in sorted(os.scandir(p), key=lambda e: e.name)
                           if e.is_file())
        except OSError:
            sig.append((str(p), None))
    return tuple(sig)


def _signature(key: tuple):
    """Abhängigkeiten pro study-Befehl. None = nur zeitbasiert (z. B. Moodle-API)."""
    cmd = key[0] if key else ""
    pd = project_dir()
    if cmd == "termine":
        return _mtimes(pd / "termine")
    if cmd == "projekte":
        return _mtimes(pd / "termine", pd / "projekte", data_dir() / "moodle_state.db")
    if cmd in ("pending", "new-files", "courses"):
        return _mtimes(data_dir() / "moodle_state.db", pd / "klassen.yaml", pd / "state")
    if cmd == "suche":
        return _mtimes(pd / "state")
    return None


def _memo(key: tuple, compute, signature=None):
    """Allgemeiner Zwischenspeicher (stale-while-revalidate, siehe oben)."""
    sig = signature() if signature else None
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None and hit[2] == sig:
        age = time.monotonic() - hit[0]
        if age < CACHE_FRESH_S:
            return hit[1]
        if age < CACHE_MAX_AGE_S:
            _refresh_in_background(key, compute, signature)
            return hit[1]
    return _refresh(key, compute, signature)


def _refresh(key: tuple, compute, signature=None):
    with _cache_lock:
        lock = _key_locks.setdefault(key, threading.Lock())
    started = time.monotonic()
    with lock:
        # Wer gewartet hat, nimmt das Ergebnis des Laufs, der gerade fertig wurde
        with _cache_lock:
            hit = _cache.get(key)
        if hit is not None and hit[0] >= started:
            return hit[1]
        sig = signature() if signature else None
        data = compute()
        with _cache_lock:
            _cache[key] = (time.monotonic(), data, sig)
        return data


def _refresh_in_background(key: tuple, compute, signature=None) -> None:
    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def work():
        try:
            _refresh(key, compute, signature)
        except Exception:
            pass
        finally:
            with _cache_lock:
                _refreshing.discard(key)

    threading.Thread(target=work, daemon=True).start()


def cached_study(*args: str, timeout: int = 90) -> list:
    """Wie ``run_study``, aber mit Zwischenspeicher pro Argumentliste."""
    return _memo(args, lambda: run_study(*args, timeout=timeout), lambda: _signature(args))


def cache_invalidate(*commands: str) -> None:
    """Verwirft nur die Einträge der genannten study-Befehle bzw. Schlüssel-Präfixe."""
    with _cache_lock:
        for key in list(_cache):
            if key and key[0] in commands:
                _cache.pop(key, None)


def cache_clear() -> None:
    """Leert den ganzen Speicher (Tests, Notfall)."""
    with _cache_lock:
        _cache.clear()


def cache_after_upload() -> None:
    """Nach einem Upload: neue Datei ändert „Zu verarbeiten“, neue Dateien und den Dateibaum.
    Termine, Deadlines, Noten und Projekte bleiben im Speicher (vorher: alles geleert)."""
    cache_invalidate("pending", "new-files", "courses", "files_tree")


def _parallel(*calls: tuple) -> list:
    """Mehrere study-Aufrufe gleichzeitig; Ergebnisse in Aufrufreihenfolge."""
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(lambda a: cached_study(*a), calls))


# Tage, mit denen das Frontend den Kalender lädt (Calendar.jsx: calendar?days=180)
CALENDAR_DAYS_FRONTEND = 180


def warm_cache() -> None:
    """Füllt den Speicher für die Standardansichten im Hintergrund vor."""
    def work():
        steps = (
            overview_data,
            lambda: calendar_events(days=CALENDAR_DAYS_FRONTEND),
            lambda: cached_study("grades", "--json"),
            files_tree_cached,
        )
        for step in steps:
            try:
                step()
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------------------
# Übersicht / Kalender / ICS
# ---------------------------------------------------------------------------

def overview_data(days: int = 14) -> dict:
    deadlines, termine, pending, new_files = _parallel(
        ("deadlines", "--days", str(days), "--json"),
        ("termine", "--days", str(days), "--json"),
        ("pending", "--json"),
        ("new-files", "--json"),
    )
    return {"deadlines": deadlines, "termine": termine, "pending": pending, "new_files": new_files}


def calendar_events(days: int = 120, vergangen: int = 0) -> list:
    """Zusammengeführte Deadlines (Moodle) und Termine (termine/*.yaml).

    vergangen: auch Termine der letzten Tage (nur termine/*.yaml; Moodle liefert nur kommende Fristen).
    """
    termine_args = ("termine", "--days", str(days), "--json") + (("--vergangen", str(vergangen)) if vergangen else ())
    deadlines, termine = _parallel(("deadlines", "--days", str(days), "--json"), termine_args)
    _plugin_imports()
    from study_agent.server.dashboard.routes_calendar import merge_calendar_events
    return merge_calendar_events(deadlines, termine)


def _ics_escape(text: str) -> str:
    return (str(text)
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _ics_fold(line: str) -> list[str]:
    """RFC 5545 Zeilenumbruch bei 75 Oktetten."""
    if len(line.encode("utf-8")) <= 75:
        return [line]
    out: list[str] = []
    current = ""
    for ch in line:
        candidate = current + ch
        if len(candidate.encode("utf-8")) > 74:
            out.append(current)
            current = " " + ch
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def _parse_due(value) -> Optional[datetime]:
    """ISO-Zeitstempel (``2026-11-09 22:59:00+00:00`` oder mit ``T``) -> aware datetime."""
    if not value:
        return None
    raw = str(value).strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _ics_event_lines(event: dict) -> list[str]:
    due = _parse_due(event.get("due"))
    summary = str(event.get("name") or "Termin")
    course = str(event.get("course") or "")
    kind = str(event.get("kind") or "")
    source = str(event.get("source") or "")
    url = str(event.get("url") or "")
    all_day = bool(event.get("all_day"))
    uid = "studium-{}-{}-{}".format(
        event.get("course_id", 0), str(event.get("due", "")), summary)

    lines: list[str] = ["BEGIN:VEVENT", "UID:{}".format(_ics_escape(uid))]
    lines.append("SUMMARY:{}".format(_ics_escape(summary)))
    desc = course
    if kind:
        desc = (desc + " · " if desc else "") + kind
    if source:
        desc = (desc + " · " if desc else "") + source
    if desc:
        lines.append("DESCRIPTION:{}".format(_ics_escape(desc)))
    if url:
        lines.append("URL:{}".format(url))
    if due is not None:
        if all_day:
            day = due.astimezone(TZ).date()
            lines.append("DTSTART;VALUE=DATE:{:%Y%m%d}".format(day))
        else:
            lines.append("DTSTART:{:%Y%m%dT%H%M%SZ}".format(due.astimezone(timezone.utc)))
            lines.append("DTEND:{:%Y%m%dT%H%M%SZ}".format(
                (due + timedelta(hours=1)).astimezone(timezone.utc)))
    lines.append("END:VEVENT")
    folded: list[str] = []
    for line in lines:
        folded.extend(_ics_fold(line))
    return folded


def ics_text(days: int = 365) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Study Agent//Studium Cockpit//DE",
        "CALSCALE:GREGORIAN",
    ]
    for event in calendar_events(days=days):
        lines.extend(_ics_event_lines(event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Kanban-Zustand
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Kursmaterial (lernen/)
# ---------------------------------------------------------------------------

def _lernen_dir() -> Path:
    return project_dir() / "lernen"


def kurse_listing() -> list:
    """Kurse mit Lernartefakten (lernen/<Kurs>/) plus eigene Module, auch wenn noch leer."""
    from study_agent.pipeline.module import QUELLE_EIGENE, QUELLE_MOODLE, eigene_module
    lernen = _lernen_dir()
    eigene = eigene_module(data_dir())
    ordner = {p.name: p for p in lernen.iterdir() if p.is_dir()} if lernen.is_dir() else {}
    out = []
    for name in sorted(set(ordner) | set(eigene)):
        course_dir = ordner.get(name, lernen / name)
        sections = []
        for section_dir in sorted(course_dir.iterdir()) if course_dir.is_dir() else []:
            if not section_dir.is_dir():
                continue
            files = sorted(f.name for f in section_dir.glob("*.md"))
            if files:
                sections.append({"name": section_dir.name, "files": files})
        out.append({
            "name": name,
            "quelle": QUELLE_EIGENE if name in eigene else QUELLE_MOODLE,
            "sections": sections,
            "begriffe": (course_dir / "begriffe.md").exists(),
            "projekt": (course_dir / "projekt.md").exists(),
            "pruefung": (course_dir / "pruefung.md").exists(),
        })
    return out


def kurs_file(course: str, rel: str) -> str:
    """Liest eine Markdown-Datei unter ``lernen/<course>/<rel>`` (nur lesend)."""
    base = (_lernen_dir() / course).resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Pfad liegt ausserhalb des Kursordners")
    if not target.is_file() or target.suffix.lower() != ".md":
        raise ValueError("Keine Markdown-Datei")
    return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Suche
# ---------------------------------------------------------------------------

def suche(frage: str, course: Optional[str] = None, limit: int = 5) -> list:
    args = ["suche", frage, "--json", "--limit", str(limit)]
    if course:
        args += ["--course", course]
    return cached_study(*args)


# ---------------------------------------------------------------------------
# Projekte
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Eigene Dokumente (Teams-Material)
# ---------------------------------------------------------------------------

MAX_UPLOAD = 50 * 1024 * 1024  # 50 MB
EIGENE_EXTENSIONS = {".pdf", ".pptx", ".docx", ".xlsx"}


def eigener_upload(course: str, filename: str, data: bytes) -> dict:
    """Speichert einen Upload über die study-CLI nach _eigene/<Kurs>/<Datei>.

    Die eigentliche Ablage (Endungs- und Grössenprüfung, Dedup per Datum) macht
    ``study eigene-upload``; hier wird nur früh validiert, damit die Antwort
    einen klaren Fehler statt einer riesigen Datei produziert.
    """
    path = Path(filename or "")
    name = path.name
    suffix = path.suffix.lower()
    if suffix not in EIGENE_EXTENSIONS:
        raise ValueError(f"{name or filename}: nur {', '.join(sorted(EIGENE_EXTENSIONS))} erlaubt")
    if len(data) > MAX_UPLOAD:
        raise ValueError(f"{name or filename}: grösser als 50 MB")
    if not data:
        raise ValueError("Datei ist leer")
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        tmp_path = Path(tmp_dir.name) / name
        tmp_path.write_bytes(data)
        proc = _run_study_proc("eigene-upload", "--course", course, str(tmp_path), "--json")
        if proc is None:
            raise ValueError("study-CLI nicht verfügbar")
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            raise ValueError((proc.stderr or "").strip() or out or "Upload fehlgeschlagen")
        # Neue Datei ändert „Zu verarbeiten“, neue Dateien und den Dateibaum
        cache_after_upload()
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            raise ValueError(f"Unerwartete Antwort der study-CLI: {out[:200]}")
    finally:
        tmp_dir.cleanup()


# ---------------------------------------------------------------------------
# Dateien (Lern-Workspace)
# ---------------------------------------------------------------------------
#
# Drei Wurzeln: ``moodle`` (Kursdateien, nur lesen), ``lernen`` und
# ``knowledge`` (nur ``*.folien.md`` und ``INDEX.md``). Bearbeitbar sind nur
# ``lernen/**/*.md`` und ``knowledge/**/*.folien.md``. Vor jedem Überschreiben
# landet eine Kopie unter ``state/versionen/<root>/<pfad>/<zeitstempel>.md``.

FILE_ROOTS = ("moodle", "lernen", "knowledge")

# Verzeichnisse, die nirgends angezeigt werden (venvs, Caches, Abhängigkeiten).
_SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "venv"}
# Werkzeug-Ordner von moodle-dl auf oberster Ebene, keine Kurse.
_MOODLE_SKIP_TOP = {"setup", "docs"}
# Nie ausliefern: Moodle-Token, Zustands-DB, Logs.
_DENY_NAMES = {"config.json"}
_DENY_SUFFIXES = {".db", ".log", ".sqlite"}
# Kursdateien, die im Moodle-Baum erscheinen.
_MOODLE_SUFFIXES = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".md", ".txt",
    ".ipynb", ".py", ".r", ".sql", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".svg", ".html", ".htm", ".bpmn", ".zip", ".mp4",
}
# Als Text lesbar (GET /files/read).
TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".csv", ".py", ".json"}
MAX_TEXT = 5 * 1024 * 1024  # 5 MB

_VERSION_ID = re.compile(r"^\d{8}T\d{12}Z(-\d+)?$")
_WRITE_LOCK = threading.Lock()


class DateiFehler(Exception):
    """Fehler der Datei-Routen; ``status`` ist der HTTP-Code."""
    status = 400


class DateiNichtGefunden(DateiFehler):
    status = 404


class NichtBearbeitbar(DateiFehler):
    status = 403


class Konflikt(DateiFehler):
    """Die Datei wurde seit dem Lesen verändert (optimistische Sperre)."""
    status = 409

    def __init__(self, message: str, current: Optional[dict]):
        super().__init__(message)
        self.current = current


def root_dir(root: str) -> Path:
    if root == "moodle":
        return data_dir()
    if root in ("lernen", "knowledge"):
        return project_dir() / root
    raise DateiFehler(f"Unbekannte Wurzel: {root}")


def _versions_dir() -> Path:
    return project_dir() / "state" / "versionen"


def _dir_visible(root: str, name: str, top: bool) -> bool:
    if name.startswith(".") or name in _SKIP_DIRS:
        return False
    if root == "moodle" and top and name in _MOODLE_SKIP_TOP:
        return False
    return True


def _file_visible(root: str, name: str, top: bool) -> bool:
    lower = name.lower()
    suffix = Path(lower).suffix
    if name.startswith(".") or lower in _DENY_NAMES or suffix in _DENY_SUFFIXES:
        return False
    if root == "moodle":
        # Auf oberster Ebene liegen nur Werkzeugdateien von moodle-dl.
        return not top and suffix in _MOODLE_SUFFIXES
    if root == "knowledge":
        return name == "INDEX.md" or lower.endswith(".folien.md")
    return True


def is_editable(root: str, rel: str) -> bool:
    lower = rel.lower()
    if root == "lernen":
        return lower.endswith(".md")
    if root == "knowledge":
        return lower.endswith(".folien.md")
    return False


def file_kind(name: str) -> str:
    suffix = Path(name.lower()).suffix
    if suffix == ".md":
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "other"


def resolve_file(root: str, rel: str) -> Path:
    """Absoluter Pfad zu ``<root>/<rel>``; wirft ``DateiFehler`` bei Ausbruch
    aus der Wurzel oder bei versteckten Dateien (z. B. ``config.json``)."""
    base = root_dir(root).resolve()
    rel = (rel or "").strip()
    if not rel or Path(rel).is_absolute() or "\x00" in rel:
        raise DateiFehler("Ungültiger Pfad")
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or target == base:
        raise DateiFehler("Pfad liegt ausserhalb der Wurzel")
    parts = target.relative_to(base).parts
    for i, part in enumerate(parts[:-1]):
        if not _dir_visible(root, part, top=(i == 0)):
            raise DateiFehler("Pfad nicht erlaubt")
    if not _file_visible(root, parts[-1], top=(len(parts) == 1)):
        raise DateiFehler("Datei nicht erlaubt")
    return target


def _rel(root: str, path: Path) -> str:
    return path.relative_to(root_dir(root).resolve()).as_posix()


def _meta(root: str, path: Path) -> dict:
    st = path.stat()
    rel = _rel(root, path)
    return {
        "root": root,
        "path": rel,
        "name": path.name,
        "type": "file",
        "kind": file_kind(path.name),
        "size": st.st_size,
        "mtime": st.st_mtime,
        # Als String: Nanosekunden sprengen die Genauigkeit von JS-Zahlen.
        "mtime_ns": str(st.st_mtime_ns),
        "editable": is_editable(root, rel),
    }


def _walk(root: str, base: Path, directory: Path, top: bool) -> list:
    try:
        entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except OSError:
        return []
    out = []
    for entry in entries:
        if entry.is_symlink():
            continue
        path = Path(entry.path)
        if entry.is_dir():
            if not _dir_visible(root, entry.name, top):
                continue
            children = _walk(root, base, path, top=False)
            if not children:
                continue
            st = entry.stat()
            out.append({
                "name": entry.name,
                "path": path.relative_to(base).as_posix(),
                "type": "dir",
                "size": None,
                "mtime": st.st_mtime,
                "editable": False,
                "children": children,
            })
        elif entry.is_file() and _file_visible(root, entry.name, top):
            st = entry.stat()
            rel = path.relative_to(base).as_posix()
            out.append({
                "name": entry.name,
                "path": rel,
                "type": "file",
                "kind": file_kind(entry.name),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "editable": is_editable(root, rel),
            })
    return out


def files_tree(roots: Optional[list] = None) -> dict:
    """Baum der drei Wurzeln (leere Ordner ausgeblendet, Symlinks übersprungen)."""
    out = []
    for root in roots or FILE_ROOTS:
        if root not in FILE_ROOTS:
            raise DateiFehler(f"Unbekannte Wurzel: {root}")
        base = root_dir(root).resolve()
        out.append({
            "root": root,
            # Absoluter Pfad, damit der Chat Dateien für den Agenten benennen kann.
            "dir": str(base),
            "editable": root != "moodle",
            "children": _walk(root, base, base, top=True) if base.is_dir() else [],
        })
    return {"roots": out}


def files_tree_cached(roots: Optional[list] = None) -> dict:
    """files_tree mit Zwischenspeicher: der Gang über die Moodle-Kursdateien (HDD)
    dauert auf dem Pi ~5 s. Schreiben, Wiederherstellen und Upload verwerfen ihn."""
    key = ("files_tree", tuple(roots or ()))
    return _memo(key, lambda: files_tree(roots))


def files_read(root: str, rel: str) -> dict:
    path = resolve_file(root, rel)
    if not path.is_file():
        raise DateiNichtGefunden("Datei nicht gefunden")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise DateiFehler("Keine Textdatei, bitte /files/raw verwenden")
    if path.stat().st_size > MAX_TEXT:
        raise DateiFehler("Datei zu gross für die Textansicht")
    return {**_meta(root, path), "content": path.read_text(encoding="utf-8", errors="replace")}


def files_raw_path(root: str, rel: str) -> Path:
    path = resolve_file(root, rel)
    if not path.is_file():
        raise DateiNichtGefunden("Datei nicht gefunden")
    return path


def _version_folder(root: str, rel: str) -> Path:
    return _versions_dir() / root / rel


def _backup(root: str, rel: str, path: Path) -> Optional[str]:
    """Kopiert den aktuellen Stand nach ``state/versionen``; liefert die Versions-ID."""
    if not path.is_file():
        return None
    folder = _version_folder(root, rel)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    vid, n = stamp, 1
    while (folder / f"{vid}.md").exists():
        vid = f"{stamp}-{n}"
        n += 1
    (folder / f"{vid}.md").write_bytes(path.read_bytes())
    return vid


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _check_writable(root: str, rel: str) -> Path:
    path = resolve_file(root, rel)
    if not is_editable(root, _rel(root, path)):
        raise NichtBearbeitbar("Datei ist nicht bearbeitbar")
    return path


def _check_mtime(root: str, path: Path, mtime_ns: Optional[str]) -> None:
    """Optimistische Sperre: ``mtime_ns`` muss dem Stand auf der Platte entsprechen.
    ``None`` heisst „neue Datei“ und ist nur erlaubt, wenn es sie noch nicht gibt."""
    exists = path.is_file()
    if mtime_ns is None:
        if exists:
            raise Konflikt("Datei existiert bereits", _meta(root, path))
        return
    if not exists:
        raise Konflikt("Datei wurde inzwischen gelöscht", None)
    if str(path.stat().st_mtime_ns) != str(mtime_ns):
        raise Konflikt("Datei wurde inzwischen geändert", _meta(root, path))


def files_write(root: str, rel: str, content: str, mtime_ns: Optional[str]) -> dict:
    path = _check_writable(root, rel)
    if len(content.encode("utf-8")) > MAX_TEXT:
        raise DateiFehler("Inhalt zu gross")
    with _WRITE_LOCK:
        _check_mtime(root, path, mtime_ns)
        version = _backup(root, _rel(root, path), path)
        _atomic_write(path, content)
        return {**_meta(root, path), "version": version}


def files_versions(root: str, rel: str) -> list:
    path = resolve_file(root, rel)
    folder = _version_folder(root, _rel(root, path))
    if not folder.is_dir():
        return []
    out = []
    for f in folder.glob("*.md"):
        if not _VERSION_ID.match(f.stem):
            continue
        st = f.stat()
        created = datetime.strptime(f.stem[:21], "%Y%m%dT%H%M%S%f").replace(tzinfo=timezone.utc)
        out.append({"id": f.stem, "size": st.st_size, "created": created.isoformat()})
    out.sort(key=lambda v: v["id"], reverse=True)
    return out


def _version_file(root: str, rel: str, version: str) -> Path:
    if not _VERSION_ID.match(version or ""):
        raise DateiFehler("Ungültige Versions-ID")
    path = resolve_file(root, rel)
    f = _version_folder(root, _rel(root, path)) / f"{version}.md"
    if not f.is_file():
        raise DateiNichtGefunden("Version nicht gefunden")
    return f


def files_version_read(root: str, rel: str, version: str) -> dict:
    f = _version_file(root, rel, version)
    created = None
    if _VERSION_ID.match(version or ""):
        try:
            created = datetime.strptime(version[:21], "%Y%m%dT%H%M%S%f").replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            created = None
    return {"root": root, "path": rel, "id": version, "created": created, "content": f.read_text(encoding="utf-8", errors="replace")}


def files_restore(root: str, rel: str, version: str, mtime_ns: Optional[str] = None) -> dict:
    """Stellt eine Version wieder her. Der aktuelle Stand wird vorher selbst
    als Version gesichert, damit sich die Wiederherstellung rückgängig machen lässt.
    Ohne ``mtime_ns`` wird nicht auf Konflikte geprüft."""
    path = _check_writable(root, rel)
    f = _version_file(root, rel, version)
    with _WRITE_LOCK:
        if mtime_ns is not None:
            _check_mtime(root, path, mtime_ns)
        backup = _backup(root, _rel(root, path), path)
        _atomic_write(path, f.read_text(encoding="utf-8"))
        return {**_meta(root, path), "version": backup, "restored": version}


def raw_headers(path: Path) -> tuple[str, str, dict]:
    """Content-Type, Disposition und Zusatz-Header für /files/raw."""
    import mimetypes

    suffix = path.suffix.lower()
    media = {".md": "text/markdown; charset=utf-8", ".ipynb": "application/json",
             ".bpmn": "application/xml"}.get(suffix)
    if media is None:
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    inline = suffix == ".pdf" or file_kind(path.name) in ("image", "text", "markdown")
    headers = {"X-Content-Type-Options": "nosniff"}
    if suffix != ".pdf":
        # HTML/SVG aus dem Kursmaterial dürfen im Dashboard-Origin kein Skript ausführen.
        # PDFs ausgenommen: Chrome zeigt PDFs in Sandbox-Frames nicht an.
        headers["Content-Security-Policy"] = "sandbox"
    return media, "inline" if inline else "attachment", headers


# ---------------------------------------------------------------------------
# FastAPI-Router (nur wenn fastapi verfügbar)
# ---------------------------------------------------------------------------

def _make_router():
    from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, Response

    router = APIRouter()
    warm_cache()

    from study_agent.server.dashboard import routes_calendar, routes_upload
    routes_calendar.project_dir_fn = project_dir
    routes_upload.data_dir_fn = data_dir
    routes_upload.cache_clear_fn = cache_after_upload
    router.include_router(routes_calendar.router)
    router.include_router(routes_upload.router)

    @router.get("/overview")
    def get_overview():
        return {
            "data": overview_data(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @router.get("/calendar")
    def get_calendar(days: int = Query(120, ge=1, le=400), vergangen: int = Query(0, ge=0, le=400)):
        return {"events": calendar_events(days=days, vergangen=vergangen), "days": days, "vergangen": vergangen}

    @router.get("/calendar.ics")
    def get_ics():
        return Response(
            content=ics_text(),
            media_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="studium.ics"'},
        )

    @router.get("/kurse")
    def get_kurse():
        return {"kurse": kurse_listing()}

    @router.post("/kurse/upload")
    async def post_kurs_upload(course: str = Form(...), file: UploadFile = File(...)):
        data = await file.read()
        try:
            result = eigener_upload(course, file.filename or "", data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, **result}

    @router.get("/kurs/{course}/datei")
    def get_kurs_datei(course: str, rel: str = Query(..., description="Relativer Pfad ab lernen/<course>/")):
        try:
            return {"course": course, "rel": rel, "content": kurs_file(course, rel)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except OSError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/fragen")
    def get_fragen(q: str = Query(..., min_length=1), course: Optional[str] = Query(None),
                   limit: int = Query(5, ge=1, le=50)):
        return {"treffer": suche(q, course=course, limit=limit)}

    # --- Dateien (Lern-Workspace) -----------------------------------------

    async def _datei(fn, *args):
        """Führt blockierende Dateiarbeit im Thread aus und übersetzt Fehler."""
        try:
            return await asyncio.to_thread(fn, *args)
        except Konflikt as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "current": exc.current})
        except DateiFehler as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Datei ist kein UTF-8-Text")
        except OSError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/files/tree")
    async def get_files_tree(root: Optional[str] = Query(None, description="Nur diese Wurzel")):
        return await _datei(files_tree_cached, [root] if root else None)

    @router.get("/files/read")
    async def get_files_read(root: str = Query(...), path: str = Query(...)):
        return await _datei(files_read, root, path)

    @router.get("/files/raw")
    async def get_files_raw(root: str = Query(...), path: str = Query(...)):
        target = await _datei(files_raw_path, root, path)
        media, disposition, headers = raw_headers(target)
        return FileResponse(target, media_type=media, filename=target.name,
                            content_disposition_type=disposition, headers=headers)

    @router.put("/files/write")
    async def put_files_write(payload: dict = Body(...)):
        content = payload.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="content fehlt")
        mtime_ns = payload.get("mtime_ns")
        result = await _datei(files_write, str(payload.get("root") or ""), str(payload.get("path") or ""),
                              content, None if mtime_ns is None else str(mtime_ns))
        cache_invalidate("files_tree")
        return result

    @router.get("/files/versions")
    async def get_files_versions(root: str = Query(...), path: str = Query(...)):
        return {"versions": await _datei(files_versions, root, path)}

    @router.get("/files/version")
    async def get_files_version(root: str = Query(...), path: str = Query(...), id: str = Query(...)):
        return await _datei(files_version_read, root, path, id)

    @router.post("/files/restore")
    async def post_files_restore(payload: dict = Body(...)):
        mtime_ns = payload.get("mtime_ns")
        result = await _datei(files_restore, str(payload.get("root") or ""), str(payload.get("path") or ""),
                              str(payload.get("id") or ""), None if mtime_ns is None else str(mtime_ns))
        cache_invalidate("files_tree")
        return result

    from study_agent.server.dashboard.routes_explorer import register_routes as register_explorer_routes
    register_explorer_routes(router, get_settings, cached_study)

    from study_agent.server.dashboard.routes_karten import register_routes as register_karten_routes
    register_karten_routes(router, get_settings)

    from study_agent.server.dashboard.routes_modul import register_routes as register_modul_routes
    register_modul_routes(router, get_settings, cached_study, calendar_events)

    from study_agent.server.dashboard.routes_agent import register_routes as register_agent_routes
    register_agent_routes(router, get_settings, cache_invalidate)

    from study_agent.server.dashboard.routes_studium import register_routes as register_studium_routes
    register_studium_routes(router, get_settings, cached_study, calendar_events, cache_invalidate)

    from study_agent.server.dashboard.routes_moodle import register_routes as register_moodle_routes
    register_moodle_routes(router, get_settings, cached_study, cache_invalidate)

    return router


def make_router():
    return _make_router()
