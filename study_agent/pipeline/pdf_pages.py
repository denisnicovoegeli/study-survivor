"""PDF Seite für Seite: Text ohne Vorlagen-Fusszeilen, Seitenformat und Marke „visuell“."""
import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

VISUAL_IMAGE_RATIO = 0.15  # Bilder bedecken mindestens 15 % der Seite
VISUAL_EXTRA_VECTORS = 40  # deutlich mehr Vektorgrafik als die Vorlage (Median aller Seiten)
FOOTER_SHARE = 0.5  # Zeilen auf mehr als der Hälfte der Seiten gelten als Fusszeile
MIN_PAGES_FOR_FOOTER = 4


@dataclass(frozen=True)
class PageInfo:
    number: int
    title: str
    text: str
    landscape: bool
    image_ratio: float
    vectors: int
    visual: bool


def _image_ratio(page) -> float:
    width, height = float(page.width), float(page.height)
    covered = 0.0
    for im in page.images:
        w = max(0.0, min(float(im["x1"]), width) - max(float(im["x0"]), 0.0))
        h = max(0.0, min(float(im["bottom"]), height) - max(float(im["top"]), 0.0))
        covered += w * h
    return min(1.0, covered / (width * height or 1.0))


def _key(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split()).casefold())


def _is_footer(key: str, footer: set[str], footer_tokens: list[set[str]]) -> bool:
    """Exakte Fusszeile oder eine Variante davon (z.B. nur „www.fhnw.ch/wirtschaft 3“).
    Reine Zahlenzeilen bleiben stehen, sonst gingen Tabellenwerte verloren."""
    if key in footer:
        return True
    tokens = set(key.split())
    return tokens != {"#"} and any(tokens <= ft for ft in footer_tokens)


def extract_pages(path: Path) -> list[PageInfo]:
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)  # „Cannot set stroke color …“ verstopft sonst das Log
    raw = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = (page.extract_text() or "").splitlines()
            vectors = len(page.curves) + len(page.rects) + len(page.lines)
            raw.append((lines, page.width > page.height, _image_ratio(page), vectors))
    if not raw:
        return []
    footer: set[str] = set()
    if len(raw) >= MIN_PAGES_FOR_FOOTER:
        counts = Counter(k for lines, *_ in raw for k in {_key(line) for line in lines if line.strip()})
        footer = {k for k, n in counts.items() if n > FOOTER_SHARE * len(raw)}
    footer_tokens = [set(k.split()) for k in footer]
    baseline = statistics.median(vectors for *_, vectors in raw)
    pages = []
    for number, (lines, landscape, ratio, vectors) in enumerate(raw, start=1):
        body = [line.rstrip() for line in lines if line.strip() and not _is_footer(_key(line), footer, footer_tokens)]
        pages.append(PageInfo(
            number=number,
            title=body[0].strip()[:80] if body else "",
            text="\n".join(body),
            landscape=landscape,
            image_ratio=round(ratio, 3),
            vectors=vectors,
            visual=ratio >= VISUAL_IMAGE_RATIO or vectors > baseline + VISUAL_EXTRA_VECTORS,
        ))
    return pages


def render_pages(pages: list[PageInfo]) -> str:
    blocks = []
    for p in pages:
        heading = f"## Seite {p.number}" + (f" · {p.title}" if p.title else "")
        marker = f"<!-- seite: {p.number}{' · visuell' if p.visual else ''} -->"
        blocks.append("\n".join([heading, marker, p.text]).rstrip())
    return "\n\n".join(blocks)
