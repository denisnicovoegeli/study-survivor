from datetime import datetime, timezone
from pathlib import Path

import pytest

from study_agent.pipeline.eigene import (EIGENE_DIR, EigeneFile, advance_eigene_state, eigene_files,
                                eigene_new_files, read_eigene_state, save_eigene_file)


def test_save_stores_under_kurs_und_behaelt_originalname(tmp_path):
    data = tmp_path / "moodle"
    dest = save_eigene_file(data, "Reinforcement Learning", "VL01.pdf", b"%PDF-1.4")
    assert dest == data / EIGENE_DIR / "Reinforcement Learning" / "VL01.pdf"
    assert dest.read_bytes() == b"%PDF-1.4"


def test_save_kuerzt_pfadanteile_und_saniert_kurs(tmp_path):
    data = tmp_path / "moodle"
    dest = save_eigene_file(data, "  Marketing ", "/pfad/zu/Folien.pptx", b"x")
    assert dest == data / EIGENE_DIR / "Marketing" / "Folien.pptx"


def test_save_haengt_datum_an_statt_zu_ueberschreiben(tmp_path):
    data = tmp_path / "moodle"
    save_eigene_file(data, "Kurs", "a.pdf", b"erste")
    save_eigene_file(data, "Kurs", "a.pdf", b"zweite")
    stamp = datetime.now(timezone.utc).date().isoformat()
    names = {p.name for p in (data / EIGENE_DIR / "Kurs").iterdir()}
    assert names == {"a.pdf", f"a-{stamp}.pdf"}
    # dritte Datei am selben Tag -> Zähler
    save_eigene_file(data, "Kurs", "a.pdf", b"dritte")
    names = {p.name for p in (data / EIGENE_DIR / "Kurs").iterdir()}
    assert names == {"a.pdf", f"a-{stamp}.pdf", f"a-{stamp}-2.pdf"}
    # Original bleibt unangetastet
    assert (data / EIGENE_DIR / "Kurs" / "a.pdf").read_bytes() == b"erste"


def test_save_rejects_extension_and_size(tmp_path, monkeypatch):
    data = tmp_path / "moodle"
    with pytest.raises(ValueError, match="nur"):
        save_eigene_file(data, "Kurs", "datei.txt", b"x")
    with pytest.raises(ValueError, match="nur"):
        save_eigene_file(data, "Kurs", "datei.zip", b"x")
    monkeypatch.setattr("study_agent.pipeline.eigene.MAX_SIZE", 4)
    with pytest.raises(ValueError, match="50 MB"):
        save_eigene_file(data, "Kurs", "datei.pdf", b"12345")
    assert not (data / EIGENE_DIR).exists()


def test_save_rejects_ungueltigen_kurs(tmp_path):
    data = tmp_path / "moodle"
    for kurs in ("", "   ", "..", ".", "a/b", "a\\b", ".hidden"):
        with pytest.raises(ValueError, match="Kurs"):
            save_eigene_file(data, kurs, "a.pdf", b"x")


def test_eigene_files_scans_nur_erlaubte_endungen(tmp_path):
    data = tmp_path / "moodle"
    (data / EIGENE_DIR / "Kurs A" / "a.pdf").parent.mkdir(parents=True, exist_ok=True)
    (data / EIGENE_DIR / "Kurs A" / "a.pdf").write_bytes(b"x")
    (data / EIGENE_DIR / "Kurs A" / "b.pptx").write_bytes(b"x")
    (data / EIGENE_DIR / "Kurs A" / "c.txt").write_bytes(b"ignoriert")
    (data / EIGENE_DIR / "Kurs B" / "d.docx").parent.mkdir(parents=True, exist_ok=True)
    (data / EIGENE_DIR / "Kurs B" / "d.docx").write_bytes(b"x")
    # Datei direkt unter _eigene/ (ohne Kurs) wird ignoriert
    (data / EIGENE_DIR / "ohne-kurs.pdf").write_bytes(b"x")

    files = eigene_files(data)
    assert [(f.course, f.name) for f in files] == [
        ("Kurs A", "a.pdf"), ("Kurs A", "b.pptx"), ("Kurs B", "d.docx")]
    assert all(f.quelle == "eigene" and f.moodle_link("https://x") == "" for f in files)


def test_eigene_new_files_baseline_und_diff(tmp_path):
    data = tmp_path / "moodle"
    state = tmp_path / "state"
    (data / EIGENE_DIR / "Kurs" / "a.pdf").parent.mkdir(parents=True, exist_ok=True)
    (data / EIGENE_DIR / "Kurs" / "a.pdf").write_bytes(b"x")

    # Erster Lauf: keine state-Datei -> Basislinie, nichts „neu“.
    assert eigene_new_files(data, state) == []

    advance_eigene_state(data, state)
    assert eigene_new_files(data, state) == []
    assert read_eigene_state(state) == {f"{EIGENE_DIR}/Kurs/a.pdf"}

    # Neue Datei -> wird als neu gemeldet, danach übernommen.
    (data / EIGENE_DIR / "Kurs" / "b.pdf").write_bytes(b"x")
    [neu] = eigene_new_files(data, state)
    assert neu.name == "b.pdf" and neu.course == "Kurs"
    advance_eigene_state(data, state)
    assert eigene_new_files(data, state) == []


def test_eigene_file_rel_and_fields():
    f = EigeneFile("Kurs", "a.pdf", Path("/data/_eigene/Kurs/a.pdf"),
                   datetime(2026, 11, 4, tzinfo=timezone.utc))
    rel = f.rel(Path("/data"))
    assert rel is not None and rel.as_posix() == "_eigene/Kurs/a.pdf"
    assert f.rel(Path("/anders")) is None
    assert f.section == ""
