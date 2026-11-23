import json
import os
from datetime import datetime, timezone
from pathlib import Path

from study_agent.pipeline.convert import (FileMeta, convert_tree, folien_path, knowledge_path, load_manifest,
                                 write_course_indexes)
from study_agent.pipeline.moodle_db import FileRecord
from study_agent.pipeline.pdf_pages import PageInfo

COURSE = "3-26FS.W-B-BAI-020106.EN⧸VZ25 Ethik： Prüfung ｜ FS"
SITE = "https://moodle.test"


def fake_pdf_reader(path: Path) -> list[PageInfo]:
    kind = path.read_bytes()
    if kind == b"scan":
        return [PageInfo(i, "", "", True, 0.9, 0, True) for i in (1, 2)]
    if kind == b"boom":
        raise ValueError("encrypted")
    return [PageInfo(1, "Faltungen", "Faltungen\nStride", True, 0.0, 100, False),
            PageInfo(2, "Pooling", "Pooling", True, 0.3, 100, True),
            PageInfo(3, "Training", "Training", True, 0.0, 100, False)]


def fake_office(path: Path) -> str:
    return "<!-- Slide number: 1 -->\n# Start\n\n<!-- Slide number: 2 -->\n![Bild](x.jpg)" if path.suffix == ".pptx" else "DOC"


def make_src(tmp_path: Path) -> Path:
    src = tmp_path / "moodle-dl"
    week = src / COURSE / "Woche 1"
    week.mkdir(parents=True)
    (week / "Folien Übersicht.pdf").write_bytes(b"slides")
    (week / "Start-up.pptx").write_bytes(b"pptx")
    (week / "notizen.md").write_text("# Notizen")
    (week / "link.webloc").write_text("ignored")
    (src / "Anderer Kurs" / "Teil").mkdir(parents=True)
    (src / "Anderer Kurs" / "Teil" / "scan.pdf").write_bytes(b"scan")
    (src / "docs").mkdir()
    (src / "docs" / "plan.md").write_text("not course material")
    return src


def run(src, dst, **kw):
    return convert_tree(src, dst, fake_office, fake_pdf_reader, **kw)


def test_pdf_rendered_per_page_with_header_and_manifest(tmp_path):
    src, dst = make_src(tmp_path), tmp_path / "knowledge"
    rel = f"{COURSE}/Woche 1/Folien Übersicht.pdf"
    report = run(src, dst, meta={rel: FileMeta("Folien Woche 1", f"{SITE}/mod/resource/view.php?id=5")})
    text = knowledge_path(dst, Path(rel)).read_text()
    assert text.startswith(f"<!-- source: {src / rel} -->\n<!-- moodle: {SITE}/mod/resource/view.php?id=5 -->\n"
                           "# Folien Übersicht.pdf\n\n## Seite 1 · Faltungen\n")
    assert "<!-- seite: 2 · visuell -->" in text
    entry = load_manifest(dst)[rel]
    assert (entry["klasse"], entry["seiten"], entry["visuell"]) == ("folien", 3, [2])
    assert sorted(report.converted) == [f"{COURSE}/Woche 1/Folien Übersicht.pdf", f"{COURSE}/Woche 1/Start-up.pptx",
                                        f"{COURSE}/Woche 1/notizen.md"]
    assert not (dst / "docs").exists()
    assert not knowledge_path(dst, Path(f"{COURSE}/Woche 1/link.webloc")).exists()


def test_pptx_slide_markers_normalised(tmp_path):
    src, dst = make_src(tmp_path), tmp_path / "knowledge"
    run(src, dst)
    rel = f"{COURSE}/Woche 1/Start-up.pptx"
    text = knowledge_path(dst, Path(rel)).read_text()
    assert "## Seite 2\n<!-- seite: 2 -->\n![Bild](x.jpg)" in text
    assert load_manifest(dst)[rel] == {**load_manifest(dst)[rel], "klasse": "folien", "seiten": 2, "visuell": []}


def test_scanned_pdf_and_converter_errors_are_failures_without_output(tmp_path):
    src, dst = make_src(tmp_path), tmp_path / "knowledge"
    (src / "Anderer Kurs" / "Teil" / "kaputt.pdf").write_bytes(b"boom")
    report = run(src, dst)
    assert ("Anderer Kurs/Teil/scan.pdf", "kein Text extrahiert (gescannt?)") in report.failed
    assert any(key == "Anderer Kurs/Teil/kaputt.pdf" and "encrypted" in reason for key, reason in report.failed)
    assert not knowledge_path(dst, Path("Anderer Kurs/Teil/scan.pdf")).exists()
    assert "Anderer Kurs/Teil/scan.pdf" not in load_manifest(dst)


def test_unchanged_skipped_and_modified_reconverted(tmp_path):
    src, dst = make_src(tmp_path), tmp_path / "knowledge"
    run(src, dst)
    second = run(src, dst)
    assert second.converted == [] and second.skipped == 3
    pdf = src / COURSE / "Woche 1" / "Folien Übersicht.pdf"
    pdf.write_bytes(b"slides-v2")
    os.utime(pdf, ns=(pdf.stat().st_atime_ns, pdf.stat().st_mtime_ns + 1_000_000_000))
    assert run(src, dst).converted == [f"{COURSE}/Woche 1/Folien Übersicht.pdf"]


def test_force_course_filter_and_course_set(tmp_path):
    src, dst = make_src(tmp_path), tmp_path / "knowledge"
    run(src, dst)
    assert len(run(src, dst, force=True, course_filter="ethik").converted) == 3
    assert run(src, dst, force=True, courses={"Anderer Kurs"}).converted == []  # nur scan.pdf, schlägt fehl
    assert run(src, dst, force=True, courses=set()).converted == []


def record(name, section_id, section, module_type="resource", module_id=1, external_url="", course=COURSE):
    return FileRecord(1, 67648, "Ethik und Technologiefolgenabschätzung", section_id, section, module_id, module_type,
                      name, name, Path("/data") / course / section / name, external_url,
                      datetime(2026, 9, 1, tzinfo=timezone.utc), False)


def test_course_index_in_moodle_order_with_links_classes_and_status(tmp_path):
    dst = tmp_path / "knowledge"
    folien = Path(COURSE) / "Woche 1" / "Folien Übersicht.pdf"
    md = knowledge_path(dst, folien)
    md.parent.mkdir(parents=True)
    md.write_text("x")
    folien_path(dst, folien).write_text("# fertig")
    (dst / ".manifest.json").write_text(json.dumps(
        {folien.as_posix(): {"sig": [1, 1], "klasse": "unklar", "seiten": 3, "visuell": [2]}}))
    records = [
        record("Allgemein.zip", 30, "Allgemeines"),
        record("Folien Übersicht.pdf", 20, "Woche 1", module_id=5),
        record("Recording", 20, "Woche 1", module_type="url", module_id=6, external_url="https://kaggle.com/x"),
        record("fremd.pdf", 20, "Woche 1", course="Anderer Kurs"),
    ]
    written = write_course_indexes(dst, Path("/data"), records, SITE, overrides={folien.as_posix(): "folien"})
    index = (dst / COURSE / "INDEX.md").read_text()
    assert index.startswith("# Ethik und Technologiefolgenabschätzung\n\nKurs-ID 67648")
    assert index.index("## Woche 1") < index.index("## Allgemeines")  # section_id 20 vor 30
    assert ("- [Folien Übersicht.pdf](Woche%201/Folien%20%C3%9Cbersicht.pdf.md) · folien · 3 S. (1 visuell)"
            f" · ✓ verarbeitet · [Moodle]({SITE}/mod/resource/view.php?id=5)") in index
    assert f"- 🔗 Recording — https://kaggle.com/x · [Moodle]({SITE}/mod/url/view.php?id=6)" in index
    assert "- Allgemein.zip _(nicht konvertiert)_" in index
    assert len(written) == 2 and (dst / "Anderer Kurs" / "INDEX.md").exists()


def test_eigene_dateien_werden_konvertiert_mit_quelle_marker(tmp_path):
    src = tmp_path / "moodle-dl"
    (src / "_eigene" / "Reinforcement Learning").mkdir(parents=True)
    (src / "_eigene" / "Reinforcement Learning" / "VL01.pdf").write_bytes(b"slides")
    dst = tmp_path / "knowledge"
    # Auch mit --current-Filter (courses) werden eigene Dateien einbezogen.
    report = run(src, dst, courses={"Nur Aktueller Kurs"})
    rel = "_eigene/Reinforcement Learning/VL01.pdf"
    text = knowledge_path(dst, Path(rel)).read_text()
    assert text.startswith(f"<!-- source: {src / rel} -->\n<!-- quelle: eigene -->\n# VL01.pdf\n")
    assert "<!-- moodle:" not in text
    assert report.converted == [rel]


def test_eigene_kursfilter_greift_auf_kursname(tmp_path):
    src = tmp_path / "moodle-dl"
    (src / "_eigene" / "Reinforcement Learning").mkdir(parents=True)
    (src / "_eigene" / "Reinforcement Learning" / "VL.pdf").write_bytes(b"slides")
    dst = tmp_path / "knowledge"
    assert run(src, dst, force=True, course_filter="reinforcement").converted == [
        "_eigene/Reinforcement Learning/VL.pdf"]
    assert run(src, dst, force=True, course_filter="marketing").converted == []
