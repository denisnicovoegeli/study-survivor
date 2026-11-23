"""Gemeinsame Test-Helfer: eine moodle_state.db mit dem echten Schema von moodle-dl."""
import sqlite3
from pathlib import Path

SCHEMA = """CREATE TABLE files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT, course_id integer NOT NULL, course_fullname integer NOT NULL,
    module_id integer NOT NULL, section_name text NOT NULL, module_name text NOT NULL,
    content_filepath text NOT NULL, content_filename text NOT NULL, content_fileurl text NOT NULL,
    content_filesize integer NOT NULL, content_timemodified integer NOT NULL, module_modname text NOT NULL,
    content_type text NOT NULL, content_isexternalfile text NOT NULL, saved_to text NOT NULL, hash text NULL,
    time_stamp integer NOT NULL, old_file_id integer NULL, modified integer DEFAULT 0 NOT NULL,
    moved integer DEFAULT 0 NOT NULL, deleted integer DEFAULT 0 NOT NULL, notified integer DEFAULT 0 NOT NULL,
    section_id integer DEFAULT 0 NOT NULL)"""

DEFAULTS = dict(
    course_id=1, course_fullname="Kurs", module_id=1, section_name="Woche 1", module_name="Modul",
    content_filepath="/", content_filename="a.pdf",
    content_fileurl="https://moodle.test/webservice/pluginfile.php/1/mod_resource/content/1/a.pdf",
    content_filesize=1, content_timemodified=1790000000, module_modname="resource", content_type="file",
    content_isexternalfile="0", saved_to="/x/a.pdf", hash=None, time_stamp=0, old_file_id=None, modified=0,
    moved=0, deleted=0, notified=1, section_id=0,
)


def make_db(db_path: Path, rows: list[dict], schema: str = SCHEMA) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute(schema)
    for row in rows:
        values = {**DEFAULTS, **row}
        cols = ", ".join(values)
        con.execute(f"INSERT INTO files ({cols}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    con.commit()
    con.close()
    return db_path
