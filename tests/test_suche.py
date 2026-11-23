import json
import os
from pathlib import Path

import pytest

from study_agent.pipeline.suche import (_fts_query, _moodle_from_header, build_index, index_db_path, search)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


FOLIEN = """<!-- source: x · moodle: https://moodle.test/mod/resource/view.php?id=1 · extrahiert: 2026-11-04 -->
# VL01.pdf

## Folie 1 · Titel
Deep Learning

## Folie 2 · Pooling
Max-Pooling reduziert die Grösse des Feature-Maps.

## Folie 3 · Training
Training mit Backpropagation und Validation-Set.
"""

ROHTEXT = """<!-- moodle: https://moodle.test/mod/resource/view.php?id=2 -->
# Skript.pdf

## Seite 1 · Überblick
Überblick über Faltungen.

## Seite 2 · Faltungen
Faltungen mit Stride und Padding.
"""

NOTIZEN = """<!-- moodle: https://moodle.test/mod/resource/view.php?id=3 -->
# Notizen

Ohne Seitenstruktur, nur Fliesstext über Regularisierung.
"""


def make_knowledge(tmp_path: Path) -> Path:
    k = tmp_path / "knowledge"
    write(k / "Kurs A" / "Woche 1" / "VL01.pdf.folien.md", FOLIEN)
    write(k / "Kurs A" / "Woche 2" / "Skript.pdf.md", ROHTEXT)
    write(k / "Kurs B" / "Notizen.md", NOTIZEN)
    return k


def test_split_and_index_folien_und_rohtext(tmp_path):
    k = make_knowledge(tmp_path)
    state = tmp_path / "state"
    report = build_index(k, state)
    assert sorted(report.indexed) == ["Kurs A/Woche 1/VL01.pdf", "Kurs A/Woche 2/Skript.pdf", "Kurs B/Notizen"]
    hits = search(index_db_path(state), "Max-Pooling", limit=10)
    assert hits[0].quelle == "folien" and hits[0].folie == "2"
    assert hits[0].kurs == "Kurs A" and hits[0].datei == "Kurs A/Woche 1/VL01.pdf"
    assert hits[0].moodle == "https://moodle.test/mod/resource/view.php?id=1"
    assert "Feature-Map" in hits[0].text


def test_umlaute_gefaltet(tmp_path):
    k = tmp_path / "knowledge"
    write(k / "Kurs" / "W" / "A.pdf.folien.md",
          "<!-- source: x · moodle: u -->\n# A\n\n## Folie 1\nDie Grösse wird verkleinert.\n")
    state = tmp_path / "state"
    build_index(k, state)
    db = index_db_path(state)
    assert search(db, "grösse") and search(db, "grosse")
    # Umlaute im Treffer bleiben erhalten, Abfrage ohne Umlaut findet sie
    assert search(db, "grosse")[0].text == "Die Grösse wird verkleinert."
    # ß wird von FTS5 nicht zu ss gefaltet (bekannte Grenze); Schweizer Material schreibt ohnehin ss


def test_nur_geaenderte_dateien(tmp_path):
    k = make_knowledge(tmp_path)
    state = tmp_path / "state"
    first = build_index(k, state)
    assert first.indexed and first.skipped == 0
    second = build_index(k, state)
    assert second.indexed == [] and second.skipped == 3
    # Änderung -> nur diese Datei wird neu indiziert
    folien = k / "Kurs A" / "Woche 1" / "VL01.pdf.folien.md"
    folien.write_text(folien.read_text() + "\n## Folie 4 · Neu\nNeuer Inhalt.\n")
    os.utime(folien, ns=(folien.stat().st_atime_ns, folien.stat().st_mtime_ns + 1_000_000_000))
    third = build_index(k, state)
    assert third.indexed == ["Kurs A/Woche 1/VL01.pdf"] and third.skipped == 2
    # force indiziert alles neu
    assert len(build_index(k, state, force=True).indexed) == 3
    # gelöschte Datei wird entfernt
    (k / "Kurs B" / "Notizen.md").unlink()
    fourth = build_index(k, state)
    assert fourth.removed == ["Kurs B/Notizen"]


def test_folien_schlaegt_rohtext(tmp_path):
    k = tmp_path / "knowledge"
    write(k / "Kurs" / "W" / "A.pdf.md", ROHTEXT)
    write(k / "Kurs" / "W" / "A.pdf.folien.md", FOLIEN)
    state = tmp_path / "state"
    report = build_index(k, state)
    assert report.indexed == ["Kurs/W/A.pdf"]
    hits = search(index_db_path(state), "Pooling", limit=10)
    assert hits and all(h.quelle == "folien" for h in hits)
    # Begriff, der nur im Rohtext steht, wird nicht indiziert (folien schlägt rohtext)
    assert search(index_db_path(state), "Faltungen", limit=10) == []
def test_eigene_dokumente_mit_kursname_und_ohne_moodle_link(tmp_path):
    k = tmp_path / "knowledge"
    write(k / "_eigene" / "Reinforcement Learning" / "Vorlesung.pdf.md",
          "<!-- source: /x/_eigene/Reinforcement Learning/Vorlesung.pdf -->\n<!-- quelle: eigene -->\n"
          "# Vorlesung.pdf\n\n## Seite 1\nPolicy Gradient und Reward.\n")
    state = tmp_path / "state"
    build_index(k, state)
    hits = search(index_db_path(state), "Policy Gradient")
    assert hits and hits[0].kurs == "Reinforcement Learning"
    assert hits[0].moodle == ""
    assert hits[0].datei == "_eigene/Reinforcement Learning/Vorlesung.pdf"


def test_fallback_ohne_seitenstruktur(tmp_path):
    k = tmp_path / "knowledge"
    write(k / "Kurs" / "Notizen.md", NOTIZEN)
    state = tmp_path / "state"
    build_index(k, state)
    hits = search(index_db_path(state), "Regularisierung")
    assert hits and hits[0].folie == "" and hits[0].quelle == "rohtext"


def test_moodle_aus_header_beide_formate():
    assert _moodle_from_header("<!-- moodle: https://moodle.test/a -->") == "https://moodle.test/a"
    assert _moodle_from_header("<!-- source: x · moodle: https://moodle.test/b · extrahiert -->") == "https://moodle.test/b"
    assert _moodle_from_header("kein Link") == ""
    assert _moodle_from_header("<!-- quelle: eigene -->") == ""


def test_fts_query_stopwords_und_praefix():
    q = _fts_query("Wie funktioniert Max-Pooling beim Training?")
    assert "Pooling" in q and "funktioniert" in q
    assert "wie" not in q and "beim" not in q
    assert '"Pooling"*' in q  # Präfix ab 3 Zeichen
    assert _fts_query("und oder der") == ""


def test_course_filter_und_limit(tmp_path):
    k = make_knowledge(tmp_path)
    state = tmp_path / "state"
    build_index(k, state)
    db = index_db_path(state)
    assert search(db, "Faltungen", course="Kurs A") == search(db, "Faltungen", course="kurs a")
    assert all(h.kurs == "Kurs A" for h in search(db, "Faltungen", course="Kurs A", limit=5))
    assert search(db, "Faltungen", course="Kurs B") == []


# --- CLI ---


@pytest.fixture
def env(tmp_path, monkeypatch):
    proj, data = tmp_path / "proj", tmp_path / "data"
    (proj / "knowledge").mkdir(parents=True)
    monkeypatch.setenv("STUDY_DATA_DIR", str(data))
    monkeypatch.setenv("STUDY_PROJECT_DIR", str(proj))
    return proj


def run(capsys, *argv):
    from study_agent.cli import main
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_cli_index_und_suche_json(env, capsys):
    k = env / "knowledge"
    write(k / "Deep Learning" / "W5" / "VL.pdf.folien.md", FOLIEN)
    code, out, _ = run(capsys, "index")
    assert code == 0 and "indexiert: 1" in out
    code, out, _ = run(capsys, "suche", "Was ist Max-Pooling?", "--json")
    assert code == 0
    [hit] = json.loads(out)
    assert hit["quelle"] == "folien" and hit["folie"] == "2" and "Feature-Map" in hit["text"]
    # kein Treffer -> leer, aber Exit 0
    code, out, _ = run(capsys, "suche", "gibbetnich", "--json")
    assert code == 0 and json.loads(out) == []
