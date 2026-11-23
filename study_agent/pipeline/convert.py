"""Kursmaterial → knowledge/ (Rohtext pro Seite), Manifest mit Klasse und visuellen Seiten, INDEX.md pro Kurs."""
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from study_agent.pipeline.classify import classify
from study_agent.pipeline.eigene import EIGENE_DIR
from study_agent.pipeline.moodle_db import FileRecord
from study_agent.pipeline.pdf_pages import PageInfo, extract_pages, render_pages

CONVERTIBLE = {".pdf", ".pptx", ".docx", ".xlsx"}
COPYABLE = {".md", ".txt"}
EXCLUDED_TOP = {"docs"}
MANIFEST = ".manifest.json"
_SLIDE_MARKER = re.compile(r"<!-- Slide number: (\d+) -->")
_PAGE_HEADING = re.compile(r"^## Seite \d+", re.M)

Converter = Callable[[Path], str]
PdfReader = Callable[[Path], list[PageInfo]]


@dataclass(frozen=True)
class FileMeta:
    module_name: str = ""
    moodle_link: str = ""


@dataclass
class ConvertReport:
    converted: list[str] = field(default_factory=list)
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    ocr: list[str] = field(default_factory=list)  # per Texterkennung gelesen


def markitdown_converter() -> Converter:
    from markitdown import MarkItDown

    md = MarkItDown()
    return lambda path: md.convert(str(path)).text_content


def knowledge_path(knowledge_dir: Path, rel: Path) -> Path:
    return knowledge_dir / rel.parent / f"{rel.name}.md"


def folien_path(knowledge_dir: Path, rel: Path) -> Path:
    return knowledge_dir / rel.parent / f"{rel.name}.folien.md"


def load_manifest(knowledge_dir: Path) -> dict:
    path = knowledge_dir / MANIFEST
    return json.loads(path.read_text()) if path.exists() else {}


def meta_from_records(records: list[FileRecord], data_dir: Path, site_url: str) -> dict[str, FileMeta]:
    meta = {}
    for r in records:
        rel = r.rel(data_dir)
        if rel is not None:
            meta[rel.as_posix()] = FileMeta(r.module_name, r.moodle_link(site_url))
    return meta


def _sources(src_root: Path, course_filter: str | None, courses: set[str] | None):
    needle = course_filter.casefold() if course_filter else None
    for path in sorted(src_root.rglob("*")):
        rel = path.relative_to(src_root)
        top = rel.parts[0]
        if top.startswith(".") or top in EXCLUDED_TOP or not path.is_file():
            continue
        if path.suffix.lower() not in CONVERTIBLE | COPYABLE:
            continue
        if top == EIGENE_DIR:
            # Eigene Dateien: Kurs ist das zweite Element, kein Moodle-Kurs nötig.
            # Immer einbeziehen (auch mit --current); ein Kursfilter greift auf den Kursnamen.
            course = rel.parts[1].casefold() if len(rel.parts) > 1 else ""
            if needle and needle not in course:
                continue
            yield path, rel
            continue
        if needle and needle not in top.casefold():
            continue
        if courses is not None and top not in courses:
            continue
        yield path, rel


def _convert_one(src: Path, office: Converter, pdf_reader: PdfReader) -> tuple[str, list[PageInfo] | None]:
    suffix = src.suffix.lower()
    if suffix in COPYABLE:
        return src.read_text(), None
    if suffix == ".pdf":
        pages = pdf_reader(src)
        return (render_pages(pages) if any(p.text.strip() for p in pages) else ""), pages
    text = office(src)
    if suffix == ".pptx":
        text = _SLIDE_MARKER.sub(lambda m: f"## Seite {m.group(1)}\n<!-- seite: {m.group(1)} -->", text)
    return text, None


def convert_tree(src_root: Path, dst_root: Path, office: Converter, pdf_reader: PdfReader = extract_pages, *,
                 force: bool = False, course_filter: str | None = None, courses: set[str] | None = None,
                 meta: dict[str, FileMeta] | None = None, ocr: PdfReader | None = None,
                 ocr_limit: int = 0) -> ConvertReport:
    """ocr: Leser für gescannte PDFs (Vision-Modell), höchstens ocr_limit Dateien pro Aufruf."""
    dst_root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(dst_root)
    meta = meta or {}
    report = ConvertReport()

    for src, rel in _sources(src_root, course_filter, courses):
        key = rel.as_posix()
        stat = src.stat()
        signature = [stat.st_mtime_ns, stat.st_size]
        dst = knowledge_path(dst_root, rel)
        if not force and (manifest.get(key) or {}).get("sig") == signature and dst.exists():
            report.skipped += 1
            continue
        try:
            text, pages = _convert_one(src, office, pdf_reader)
        except Exception as exc:  # Konverter-Bibliotheken werfen viele verschiedene Fehler
            report.failed.append((key, f"{type(exc).__name__}: {exc}"[:200]))
            continue
        per_ocr = False
        if not text.strip() and src.suffix.lower() == ".pdf" and ocr is not None and len(report.ocr) < ocr_limit:
            try:
                pages = ocr(src)
                text = render_pages(pages) if any(p.text.strip() for p in pages) else ""
                per_ocr = bool(text.strip())
            except Exception as exc:  # Netz, Proxy, Modell: Datei bleibt für den nächsten Lauf offen
                report.failed.append((key, f"Texterkennung: {type(exc).__name__}: {exc}"[:200]))
                continue
        if not text.strip():
            grund = "kein Text extrahiert (gescannt?)"
            if src.suffix.lower() == ".pdf" and ocr is not None:
                grund += " · Texterkennung: " + ("ohne Ergebnis" if len(report.ocr) < ocr_limit
                                                  else "nicht in diesem Lauf")
            report.failed.append((key, grund))
            continue
        info = meta.get(key, FileMeta())
        if rel.parts[0] == EIGENE_DIR:
            header = [f"<!-- source: {src} -->", "<!-- quelle: eigene -->"]
        else:
            header = [f"<!-- source: {src} -->"] + ([f"<!-- moodle: {info.moodle_link} -->"] if info.moodle_link else [])
        if per_ocr:
            header.append("<!-- texterkennung: vision -->")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(header) + f"\n# {src.name}\n\n{text.rstrip()}\n")
        manifest[key] = {
            "sig": signature,
            "klasse": classify(src.name, info.module_name, src.suffix.lower(), pages),
            "seiten": len(pages) if pages is not None else (len(_PAGE_HEADING.findall(text)) or None),
            "visuell": [p.number for p in pages if p.visual] if pages else [],
        } | ({"ocr": True} if per_ocr else {})
        (dst_root / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        report.converted.append(key)
        if per_ocr:
            report.ocr.append(key)
    return report


def _index_line(r: FileRecord, rel: Path, knowledge_dir: Path, course_out: Path, manifest: dict,
                overrides: dict[str, str], site_url: str) -> str:
    moodle = f" · [Moodle]({r.moodle_link(site_url)})"
    if r.module_type == "url":
        return f"- 🔗 {r.module_name} — {r.external_url}{moodle}"
    key = rel.as_posix()
    entry = manifest.get(key)
    md = knowledge_path(knowledge_dir, rel)
    if entry is None or not md.exists():
        return f"- {r.name} _(nicht konvertiert)_{moodle}"
    klasse = overrides.get(key, entry["klasse"])
    pages = f" · {entry['seiten']} S." if entry.get("seiten") else ""
    visual = f" ({len(entry['visuell'])} visuell)" if entry.get("visuell") else ""
    done = " · ✓ verarbeitet" if folien_path(knowledge_dir, rel).exists() else ""
    link = quote(md.relative_to(course_out).as_posix())
    return f"- [{r.name}]({link}) · {klasse}{pages}{visual}{done}{moodle}"


def write_course_indexes(knowledge_dir: Path, data_dir: Path, records: list[FileRecord], site_url: str,
                         overrides: dict[str, str] | None = None) -> list[Path]:
    """Eine INDEX.md pro Kursordner, Abschnitte in Moodle-Reihenfolge (section_id), inkl. externer Links."""
    manifest = load_manifest(knowledge_dir)
    overrides = overrides or {}
    by_course: dict[str, list[tuple[FileRecord, Path]]] = {}
    for r in records:
        rel = r.rel(data_dir)
        if rel is not None and len(rel.parts) > 1:
            by_course.setdefault(rel.parts[0], []).append((r, rel))
    written = []
    for course_dir, items in sorted(by_course.items()):
        out = knowledge_dir / course_dir
        out.mkdir(parents=True, exist_ok=True)
        first = items[0][0]
        lines = [f"# {first.course}", "", f"Kurs-ID {first.course_id} · Eintrag: Klasse · Seiten (davon visuell)"
                 " · ✓ = von /verarbeiten erfasst", ""]
        items.sort(key=lambda item: (item[0].section_id, item[0].name))
        for (_, section), group in groupby(items, key=lambda item: (item[0].section_id, item[0].section)):
            lines.append(f"## {section or '(ohne Abschnitt)'}")
            lines += [_index_line(r, rel, knowledge_dir, out, manifest, overrides, site_url) for r, rel in group]
            lines.append("")
        index = out / "INDEX.md"
        index.write_text("\n".join(lines))
        written.append(index)
    return written
