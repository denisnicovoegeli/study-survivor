import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from study_agent.config import Settings
from study_agent.pipeline.pending import check_folien, finish, pending_files

SITE = "https://moodle.test"
DL = "26HS Deep Learning BAI"


def setup(tmp_path, files):
    """files: {rel: (klasse, seiten, course_id)} → Settings, Records; schreibt Manifest und Rohtext."""
    from study_agent.pipeline.moodle_db import FileRecord

    s = Settings(data_dir=tmp_path / "data", project_dir=tmp_path / "proj")
    manifest, records = {}, []
    for i, (rel, (klasse, seiten, course_id)) in enumerate(files.items(), start=1):
        manifest[rel] = {"sig": [i, i], "klasse": klasse, "seiten": seiten, "visuell": [2] if seiten else []}
        raw = s.knowledge_dir / f"{rel}.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("roh")
        parts = Path(rel).parts
        records.append(FileRecord(i, course_id, parts[0], i, parts[1], 100 + i, "resource", parts[-1], parts[-1],
                                  s.data_dir / rel, "", datetime(2026, 9, 1, tzinfo=timezone.utc), False))
    (s.knowledge_dir / ".manifest.json").write_text(json.dumps(manifest))
    return s, records


FILES = {
    f"{DL}/Woche 3/W03_training.pdf": ("folien", 3, 69210),
    f"{DL}/Programm/HS26_DeepLearning_BAI.pdf": ("semesterprogramm", 2, 69210),
    f"{DL}/Projekt/Themen.pdf": ("unklar", 3, 69210),
    f"{DL}/Woche 1/Lösung.pdf": ("loesung", 5, 69210),
    "Design Thinking SS2026/Woche 1/alt.pdf": ("folien", 10, 68158),
}


def test_pending_routes_order_and_paths(tmp_path):
    s, records = setup(tmp_path, FILES)
    pending = pending_files(s, records, {}, SITE)
    assert [(p.name, p.route) for p in pending] == [
        ("Themen.pdf", "fragen"), ("HS26_DeepLearning_BAI.pdf", "info"),
        ("W03_training.pdf", "voll"), ("alt.pdf", "voll")]
    w03 = pending[2]
    assert (w03.reason, w03.pages, w03.visual, w03.course_id) == ("neu", 3, [2], 69210)
    assert w03.source == s.data_dir / DL / "Woche 3" / "W03_training.pdf"
    assert w03.raw_md == s.knowledge_dir / DL / "Woche 3" / "W03_training.pdf.md"
    assert w03.folien_md == s.knowledge_dir / DL / "Woche 3" / "W03_training.pdf.folien.md"
    assert w03.lernen_dir == s.lernen_dir / DL / "Woche 3"
    assert w03.course_lernen_dir == s.lernen_dir / DL
    assert w03.moodle_link == f"{SITE}/mod/resource/view.php?id=101"


def test_overrides_and_course_filter(tmp_path):
    s, records = setup(tmp_path, FILES)
    overrides = {f"{DL}/Projekt/Themen.pdf": "projekt", f"{DL}/Woche 3/W03_training.pdf": "ueberspringen"}
    pending = pending_files(s, records, overrides, SITE, course_ids={69210})
    assert [(p.name, p.route, p.klasse) for p in pending] == [
        ("HS26_DeepLearning_BAI.pdf", "info", "semesterprogramm"), ("Themen.pdf", "info", "projekt")]


def write_folien(s, rel, numbers):
    path = s.knowledge_dir / f"{rel}.folien.md"
    path.write_text("# x\n\n" + "\n\n".join(f"## Folie {n} · T\ntext" for n in numbers))
    return path


def test_check_folien_reports_missing(tmp_path):
    s, _ = setup(tmp_path, FILES)
    rel = f"{DL}/Woche 3/W03_training.pdf"
    assert check_folien(s.knowledge_dir / f"{rel}.folien.md", 3) == [1, 2, 3]
    assert check_folien(write_folien(s, rel, [1, 3]), 3) == [2]
    assert check_folien(write_folien(s, rel, [1, 2, 3]), 3) == []


def test_finish_requires_complete_folien_and_marks_done(tmp_path):
    s, records = setup(tmp_path, FILES)
    rel = f"{DL}/Woche 3/W03_training.pdf"
    write_folien(s, rel, [1, 3])
    with pytest.raises(ValueError, match=r"fehlen Folien \[2\]"):
        finish(s, rel, {})
    write_folien(s, rel, [1, 2, 3])
    finish(s, rel, {})
    finish(s, f"{DL}/Programm/HS26_DeepLearning_BAI.pdf", {})  # Route „info“ braucht keine .folien.md
    assert {p.name for p in pending_files(s, records, {}, SITE)} == {"Themen.pdf", "alt.pdf"}
    with pytest.raises(ValueError, match="unklar"):
        finish(s, f"{DL}/Projekt/Themen.pdf", {})
    with pytest.raises(ValueError, match="manifest"):
        finish(s, f"{DL}/gibt-es-nicht.pdf", {})


def test_reuploaded_file_becomes_outdated(tmp_path):
    s, records = setup(tmp_path, FILES)
    rel = f"{DL}/Programm/HS26_DeepLearning_BAI.pdf"
    finish(s, rel, {})
    manifest = json.loads((s.knowledge_dir / ".manifest.json").read_text())
    manifest[rel]["sig"] = [999, 999]  # neue Version aus Moodle
    (s.knowledge_dir / ".manifest.json").write_text(json.dumps(manifest))
    [again] = [p for p in pending_files(s, records, {}, SITE) if p.rel == rel]
    assert again.reason == "veraltet"


def test_pending_enthaelt_eigene_dateien_ohne_moodle(tmp_path):
    from study_agent.pipeline.eigene import eigene_files

    s = Settings(data_dir=tmp_path / "data", project_dir=tmp_path / "proj")
    rel = "_eigene/Reinforcement Learning/VL.pdf"
    (s.data_dir / "_eigene" / "Reinforcement Learning").mkdir(parents=True)
    (s.data_dir / "_eigene" / "Reinforcement Learning" / "VL.pdf").write_bytes(b"slides")
    s.knowledge_dir.mkdir(parents=True)
    (s.knowledge_dir / ".manifest.json").write_text(json.dumps(
        {rel: {"sig": [1, 1], "klasse": "folien", "seiten": 2, "visuell": [1]}}))
    (s.knowledge_dir / f"{rel}.md").parent.mkdir(parents=True, exist_ok=True)
    (s.knowledge_dir / f"{rel}.md").write_text("roh")

    [p] = pending_files(s, [], {}, SITE, course_ids=set(), eigene=eigene_files(s.data_dir))
    assert (p.rel, p.course, p.course_id, p.section, p.route) == (
        rel, "Reinforcement Learning", -1, "", "voll")
    assert p.moodle_link == ""
    assert p.source == s.data_dir / rel
    assert p.course_lernen_dir == s.lernen_dir / "Reinforcement Learning"
