"""Einziger Zugriff auf moodle-dl's interne moodle_state.db (nur lesend)."""
import html
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

STATE_FILE = "last_file_id.txt"
REQUIRED_COLUMNS = frozenset({
    "file_id", "course_id", "course_fullname", "module_id", "section_id", "section_name", "module_name",
    "module_modname", "content_filename", "content_fileurl", "content_timemodified", "saved_to", "old_file_id",
    "deleted",
})
_SELECT = ("SELECT file_id, course_id, course_fullname, section_id, section_name, module_id, module_modname,"
           " module_name, content_filename, saved_to, content_fileurl, content_timemodified, old_file_id FROM files")
_TAG = re.compile(r"<[^>]+>")
_SECRET_PARAM = re.compile(r"token|key|secret|sig|auth|code|password|invite", re.I)


class MoodleDbError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileRecord:
    file_id: int
    course_id: int
    course: str
    section_id: int
    section: str
    module_id: int
    module_type: str  # resource | folder | url | page | assign
    module_name: str
    name: str
    path: Path
    external_url: str  # nur bei module_type == "url", Zugangsdaten entfernt; sonst leer
    modified: datetime
    updated: bool

    def moodle_link(self, site_url: str) -> str:
        return f"{site_url}/mod/{self.module_type}/view.php?id={self.module_id}"

    def rel(self, data_dir: Path) -> Path | None:
        try:
            return self.path.relative_to(data_dir)
        except ValueError:
            return None


@dataclass(frozen=True)
class Course:
    course_id: int
    name: str
    files: int
    last_modified: datetime


@dataclass(frozen=True)
class Assign:
    """Eine Moodle-Abgabe (module_modname == \"assign\"). Ohne Fälligkeitsdatum —
    das kommt aus termine/*.yaml bzw. dem Semesterprogramm."""
    course_id: int
    course: str
    module_id: int
    name: str
    section: str
    modified: datetime

    def moodle_link(self, site_url: str) -> str:
        return f"{site_url}/mod/assign/view.php?id={self.module_id}"


def clean_text(raw: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", raw)).split())


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if any(_SECRET_PARAM.search(k) for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return urlunsplit(parts._replace(query="", fragment="")) + " (Link gekürzt: enthielt Zugangsdaten)"
    return url


def _connect(db_path: Path) -> sqlite3.Connection:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        columns = {row[1] for row in con.execute("PRAGMA table_info(files)")}
    except sqlite3.Error as exc:
        raise MoodleDbError(f"{db_path.name}: {exc}") from None
    missing = REQUIRED_COLUMNS - columns
    if missing:
        con.close()
        raise MoodleDbError(f"{db_path.name}: Schema von moodle-dl geändert, Spalten fehlen: {', '.join(sorted(missing))}")
    return con


def _record(r: tuple) -> FileRecord:
    return FileRecord(
        file_id=r[0], course_id=r[1], course=str(r[2]), section_id=r[3], section=clean_text(r[4]),
        module_id=r[5], module_type=r[6], module_name=clean_text(r[7]), name=r[8], path=Path(r[9]),
        external_url=redact_url(r[10]) if r[6] == "url" else "",
        modified=datetime.fromtimestamp(r[11], tz=timezone.utc), updated=r[12] is not None,
    )


def _query(db_path: Path, where: str = "", params: tuple = ()) -> list[FileRecord]:
    with closing(_connect(db_path)) as con:
        rows = con.execute(f"{_SELECT} WHERE deleted = 0 {where}", params).fetchall()
    return sorted((_record(r) for r in rows), key=lambda f: (f.course, f.section_id, f.name))


def files_since(db_path: Path, after_file_id: int) -> list[FileRecord]:
    return _query(db_path, "AND file_id > ?", (after_file_id,))


def all_files(db_path: Path) -> list[FileRecord]:
    return _query(db_path)


def max_file_id(db_path: Path) -> int:
    with closing(_connect(db_path)) as con:
        return con.execute("SELECT COALESCE(MAX(file_id), 0) FROM files").fetchone()[0]


def courses(db_path: Path) -> list[Course]:
    with closing(_connect(db_path)) as con:
        rows = con.execute("SELECT course_id, MAX(course_fullname), COUNT(*), MAX(content_timemodified) FROM files"
                           " WHERE deleted = 0 GROUP BY course_id ORDER BY MAX(content_timemodified) DESC").fetchall()
    return [Course(r[0], str(r[1]), r[2], datetime.fromtimestamp(r[3], tz=timezone.utc)) for r in rows]


def assigns(db_path: Path, course_id: int | None = None) -> list[Assign]:
    """Alle Moodle-Abgaben (module_modname \"assign\"), optional auf einen Kurs begrenzt.

    Doppelte Zeilen desselben Moduls (moodle-dl legt sie gelegentlich an) werden
    über GROUP BY zusammengefasst. Nur lesend.
    """
    where = "AND course_id = ?" if course_id is not None else ""
    params = (course_id,) if course_id is not None else ()
    with closing(_connect(db_path)) as con:
        rows = con.execute(
            "SELECT course_id, course_fullname, module_id, module_name, section_name,"
            " MAX(content_timemodified) FROM files"
            " WHERE deleted = 0 AND module_modname = 'assign' " + where +
            " GROUP BY course_id, module_id ORDER BY course_id, module_id", params).fetchall()
    return [Assign(r[0], str(r[1]), r[2], clean_text(r[3]), clean_text(r[4]),
                   datetime.fromtimestamp(r[5], tz=timezone.utc)) for r in rows]


def semester_start(today: date) -> date:
    """Herbstsemester ab 1. August, Frühlingssemester ab 1. Februar."""
    if today.month >= 8:
        return date(today.year, 8, 1)
    if today.month >= 2:
        return date(today.year, 2, 1)
    return date(today.year - 1, 8, 1)


def current_courses(db_path: Path, today: date) -> list[Course]:
    start = datetime.combine(semester_start(today), time.min, timezone.utc)
    return [c for c in courses(db_path) if c.last_modified >= start]


def read_last_file_id(state_dir: Path) -> int | None:
    path = state_dir / STATE_FILE
    return int(path.read_text().strip()) if path.exists() else None


def write_last_file_id(state_dir: Path, file_id: int) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STATE_FILE).write_text(f"{file_id}\n")
