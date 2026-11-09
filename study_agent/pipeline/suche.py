"""Index und Volltextsuche über das Kursmaterial (SQLite FTS5, BM25).

Der Index liegt in state/suche.db und wird nie committet. Eine Zeile pro
Abschnitt: aus der .folien.md („## Folie N“), sonst pro Seite aus dem Rohtext
(„## Seite N“). Treffer tragen Kurs, Datei, Folie/Seite, Text, Moodle-Link und
Quelle („folien“ oder „rohtext“). Eigene Dokumente (Quelle „eigene“) haben
keinen Moodle-Link; ihr Kurs ist der Unterordner unter _eigene/.
"""
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from study_agent.config import load_moodle_config
from study_agent.pipeline.eigene import EIGENE_DIR
from study_agent.pipeline.moodle_db import MoodleDbError, all_files

INDEX_DB = "suche.db"
TOKENIZER = "unicode61 remove_diacritics 2"

_FOLIE_H = re.compile(r"^## Folie (\d+)(?: · (.*))?$", re.M)
_SEITE_H = re.compile(r"^## Seite (\d+)(?: · (.*))?$", re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_MOODLE = re.compile(r"moodle[:：]\s*(https?://[^\s>·]+)")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Häufige Füllwörter, die für die Suche nichts beitragen (deutsch + englisch).
STOPWORDS = frozenset("""
    der die das den dem des ein eine einen einem einer eines und oder aber nicht
    ist sind war waren wird werden wurde wurden hat haben hatte hatten wie was wo
    wann warum wer wessen welche welcher welches welchen mit ohne für fuer von zu
    zum zur auf in im an am bei beim über unter zwischen nach vor aus als auch nur
    noch schon sich sein seine ihrem ihren ihr ihre mich mir dich dir uns euch ihm
    ihn ihnen sie es er wir man kein keine kann können muss müssen soll sollen will
    wollen durch gegen um bis
    the a an and or of to in on for with is are was were be been being this that
    these those it its my your our their what which how why when where who not no
    yes do does did have has had can could should would will shall i you we they
    he she
""".split())


@dataclass(frozen=True)
class Treffer:
    kurs: str
    datei: str      # relativer Pfad ab knowledge/ (z. B. "Kurs/Abschnitt/Datei.pdf")
    folie: str      # Folien- bzw. Seitennummer, "" wenn keine Abschnitte vorhanden
    quelle: str     # "folien" | "rohtext"
    moodle: str     # Moodle-Link (leer bei eigenen Dokumenten)
    text: str


@dataclass
class IndexReport:
    indexed: list[str] = field(default_factory=list)
    skipped: int = 0
    removed: list[str] = field(default_factory=list)


def index_db_path(state_dir: Path) -> Path:
    return state_dir / INDEX_DB


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS suche USING fts5("
        f"kurs, datei, folie, quelle, moodle, text, tokenize='{TOKENIZER}')")
    con.execute("CREATE TABLE IF NOT EXISTS meta("
                "datei TEXT PRIMARY KEY, quelle TEXT NOT NULL, sig TEXT NOT NULL)")


def _moodle_from_header(text: str) -> str:
    """Moodle-Link aus dem Dateikopf, als Rückfallebene zur moodle_state.db."""
    m = _MOODLE.search(text)
    return m.group(1) if m else ""


def _clean(chunk: str) -> str:
    chunk = _COMMENT.sub("", chunk)
    return "\n".join(ln.strip() for ln in chunk.splitlines() if ln.strip())


def _fallback_section(text: str) -> str:
    """Ganze Datei als ein Abschnitt, wenn keine „## Folie/Seite N“-Überschriften."""
    text = _COMMENT.sub("", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("# ")):
        lines.pop(0)
    return "\n".join(ln.strip() for ln in lines if ln.strip())


def _split_sections(text: str, quelle: str) -> list[tuple[str, str]]:
    heading = _FOLIE_H if quelle == "folien" else _SEITE_H
    matches = list(heading.finditer(text))
    if not matches:
        body = _fallback_section(text)
        return [("", body)] if body else []
    sections = []
    for i, m in enumerate(matches):
        num = m.group(1)
        title = (m.group(2) or "").strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = _clean(text[m.end():end])
        if not body:
            body = title
        if body:
            sections.append((num, body))
    return sections


# Ordner, die nicht ins Kursmaterial gehören (z. B. hochgeladene Projekt-Repos mit .venv)
SKIP_PARTS = frozenset({".venv", "venv", "node_modules", "site-packages", "__pycache__", ".git"})


def _skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def iter_docs(knowledge_dir: Path):
    """(rel, Quelldatei, Quelle) für jede indizierbare Datei. „folien“ schlägt „rohtext“."""
    folien = {}
    for path in sorted(knowledge_dir.rglob("*.folien.md")):
        if _skip(path.relative_to(knowledge_dir)):
            continue
        key = path.relative_to(knowledge_dir).as_posix()[:-len(".folien.md")]
        folien[key] = path
    for path in sorted(knowledge_dir.rglob("*.md")):
        rel = path.relative_to(knowledge_dir)
        if rel.name == "INDEX.md" or rel.name.endswith(".folien.md") or _skip(rel):
            continue
        key = rel.as_posix()[:-len(".md")]
        if key in folien:
            continue
        yield key, path, "rohtext"
    for key, path in folien.items():
        yield key, path, "folien"


def moodle_links(settings) -> dict[str, str]:
    """rel -> Moodle-Link aus der moodle_state.db; leer, wenn die DB fehlt."""
    try:
        records = all_files(settings.moodle_db)
    except MoodleDbError:
        return {}
    site = load_moodle_config(settings.moodle_config_path).site_url
    out = {}
    for r in records:
        rel = r.rel(settings.data_dir)
        if rel is not None:
            out[rel.as_posix()] = r.moodle_link(site)
    return out


def build_index(knowledge_dir: Path, state_dir: Path, force: bool = False,
                links: dict[str, str] | None = None) -> IndexReport:
    """Indiziert nur Dateien, deren Signatur (Quelle, mtime, Grösse) sich geändert hat."""
    links = links or {}
    state_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(index_db_path(state_dir))
    try:
        _ensure_schema(con)
        sigs = {r[0]: r[2] for r in con.execute("SELECT datei, quelle, sig FROM meta")}
        report = IndexReport()
        seen: set[str] = set()
        for key, path, quelle in iter_docs(knowledge_dir):
            seen.add(key)
            sig = f"{quelle}|{path.stat().st_mtime_ns}|{path.stat().st_size}"
            if not force and sigs.get(key) == sig:
                report.skipped += 1
                continue
            text = path.read_text()
            moodle = links.get(key) or _moodle_from_header(text)
            kurs = key.split("/", 1)[0]
            if kurs == EIGENE_DIR:
                # Eigene Datei: Kurs ist der Unterordner unter _eigene/, kein Moodle-Link.
                kurs = key.split("/", 2)[1] if "/" in key else key
                moodle = ""
            con.execute("DELETE FROM suche WHERE datei = ?", (key,))
            for folie, body in _split_sections(text, quelle):
                con.execute(
                    "INSERT INTO suche(kurs, datei, folie, quelle, moodle, text) VALUES (?,?,?,?,?,?)",
                    (kurs, key, folie, quelle, moodle, body))
            con.execute(
                "INSERT INTO meta(datei, quelle, sig) VALUES (?,?,?) "
                "ON CONFLICT(datei) DO UPDATE SET quelle=excluded.quelle, sig=excluded.sig",
                (key, quelle, sig))
            report.indexed.append(key)
        stale = [k for k in sigs if k not in seen]
        for k in stale:
            con.execute("DELETE FROM suche WHERE datei = ?", (k,))
            con.execute("DELETE FROM meta WHERE datei = ?", (k,))
        report.removed = stale
        con.commit()
    finally:
        con.close()
    return report


def _fts_query(frage: str) -> str:
    """Natürliche Frage -> FTS5-Abfrage (OR der Stichwörter, Präfix ab 3 Zeichen)."""
    tokens = [t for t in _TOKEN.findall(frage)
              if t.casefold() not in STOPWORDS and len(t) >= 2]
    if not tokens:
        return ""
    seen: set[str] = set()
    parts = []
    for t in tokens:
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(f'"{t}"' + ("*" if len(t) >= 3 else ""))
    return " OR ".join(parts)


def search(db_path: Path, frage: str, course: str | None = None,
           limit: int = 5) -> list[Treffer]:
    """Volltextsuche mit BM25-Ranking; nur die Spalten Kurs, Datei und Text werden durchsucht."""
    query = _fts_query(frage)
    if not query or not db_path.exists():
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        sql = ("SELECT kurs, datei, folie, quelle, moodle, text FROM suche "
               "WHERE suche MATCH ?")
        params: list = [f"{{kurs datei text}}: {query}"]
        if course:
            sql += " AND kurs LIKE ?"
            params.append(f"%{course}%")
        sql += " ORDER BY bm25(suche) LIMIT ?"
        params.append(limit)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    return [Treffer(*row) for row in rows]


def treffer_json(hits: list[Treffer]) -> str:
    import json
    return json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2)
