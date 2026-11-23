"""Eigene, vom Nutzer hochgeladene Dokumente (Teams-Material) unter _eigene/<Kurs>/<Datei>.

Diese Dateien stehen ausserhalb von moodle-dl und werden von der study-CLI wie
Moodle-Dateien behandelt, aber mit Quelle „eigene“ statt eines Moodle-Links.
moodle-dl fasst _eigene/ nicht an; Zustand liegt in state/ (nie in moodle_state.db).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EIGENE_DIR = "_eigene"
# Nur diese Endungen sind als eigene Dokumente erlaubt (Aufgabe Teil F).
EIGENE_EXTENSIONS = frozenset({".pdf", ".pptx", ".docx", ".xlsx"})
MAX_SIZE = 50 * 1024 * 1024  # 50 MB
STATE_FILE = "eigene_state.json"


@dataclass(frozen=True)
class EigeneFile:
    """Eine eigene Datei; duck-typed kompatibel mit moodle_db.FileRecord (course, section, name, modified)."""

    course: str
    name: str
    path: Path
    modified: datetime
    section: str = ""
    quelle: str = "eigene"

    def rel(self, data_dir: Path) -> Path | None:
        try:
            return self.path.relative_to(data_dir)
        except ValueError:
            return None

    def moodle_link(self, site_url: str) -> str:
        return ""  # Quelle „eigene“ statt Moodle-Link


def eigene_dir(data_dir: Path) -> Path:
    return data_dir / EIGENE_DIR


def eigene_files(data_dir: Path) -> list[EigeneFile]:
    """Alle hochgeladenen Dateien unter _eigene/<Kurs>/<Datei>, nach Kurs und Name sortiert."""
    root = eigene_dir(data_dir)
    if not root.is_dir():
        return []
    out: list[EigeneFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EIGENE_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        if len(rel.parts) < 2:  # braucht <Kurs>/<Datei>
            continue
        out.append(EigeneFile(
            course=rel.parts[0], name=path.name, path=path,
            modified=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        ))
    return out


def _sanitize_course(course: str) -> str:
    name = course.strip()
    if not name:
        raise ValueError("Kursname fehlt")
    if name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name:
        raise ValueError(f"Ungültiger Kursname: {course!r}")
    return name


def save_eigene_file(data_dir: Path, course: str, filename: str, data: bytes, subpath: str | None = None) -> Path:
    """Speichert eine hochgeladene Datei nach _eigene/<Kurs>/[<Unterordner>/]<Datei>, ohne zu überschreiben.

    Bei gleichem Namen wird das Datum (JJJJ-MM-TT), bei erneuter Kollision ein
    Zähler angehängt. Originalname bleibt erhalten.
    Pfadschutz: Weder course noch subpath dürfen aus dem Zielverzeichnis ausbrechen.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("Daten fehlen")
    if len(data) > MAX_SIZE:
        raise ValueError(f"{filename}: grösser als 50 MB")
    path = Path(filename)
    name = path.name  # Pfadbestandteile abschneiden
    suffix = path.suffix.lower()
    if suffix not in EIGENE_EXTENSIONS:
        raise ValueError(f"{filename}: nur {', '.join(sorted(EIGENE_EXTENSIONS))} erlaubt")
    kurs = _sanitize_course(course)
    course_root = (eigene_dir(data_dir) / kurs).resolve()

    if subpath:
        raw_parts = Path(subpath).parts
        clean_parts = []
        for p in raw_parts:
            p_clean = p.strip()
            if not p_clean or p_clean in (".", "..") or p_clean.startswith("."):
                raise ValueError(f"Ungültiger Pfadbestandteil: {p!r}")
            if "/" in p_clean or "\\" in p_clean:
                raise ValueError(f"Ungültiger Pfadbestandteil: {p!r}")
            clean_parts.append(p_clean)

        # Falls subpath auch den Dateinamen am Ende enthielt, nur die Ordner davor verwenden
        if clean_parts and clean_parts[-1] == name:
            clean_parts = clean_parts[:-1]

        dest_dir = course_root.joinpath(*clean_parts)
    else:
        dest_dir = course_root

    # Pfadschutz-Prüfung: Muss unter course_root liegen
    try:
        dest_dir.resolve().relative_to(course_root)
    except ValueError:
        raise ValueError("Pfadausbruch erkannt")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.exists():
        stamp = datetime.now(timezone.utc).date().isoformat()
        stem = name[: -len(suffix)] if suffix else name
        dest = dest_dir / f"{stem}-{stamp}{suffix}"
        i = 2
        while dest.exists():
            dest = dest_dir / f"{stem}-{stamp}-{i}{suffix}"
            i += 1
    dest.write_bytes(bytes(data))
    return dest


# ---------------------------------------------------------------------------
# Zustand für „Neue Dateien“ (state/, nie in moodle_state.db)
# ---------------------------------------------------------------------------

def read_eigene_state(state_dir: Path) -> set[str]:
    path = state_dir / STATE_FILE
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(x) for x in raw} if isinstance(raw, list) else set()


def write_eigene_state(state_dir: Path, rels: set[str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STATE_FILE).write_text(json.dumps(sorted(rels), ensure_ascii=False, indent=1))


def eigene_new_files(data_dir: Path, state_dir: Path) -> list[EigeneFile]:
    """Eigene Dateien, die seit dem letzten Lauf neu dazugekommen sind.

    Erster Lauf (kein state/eigene_state.json): Basislinie, noch keine „neuen“.
    """
    if not (state_dir / STATE_FILE).exists():
        return []
    known = read_eigene_state(state_dir)
    return [f for f in eigene_files(data_dir) if f.rel(data_dir).as_posix() not in known]


def advance_eigene_state(data_dir: Path, state_dir: Path) -> None:
    """Merkt sich alle aktuellen eigenen Dateien (nach dem Briefing aufrufen)."""
    rels = {f.rel(data_dir).as_posix() for f in eigene_files(data_dir)}
    write_eigene_state(state_dir, rels)
