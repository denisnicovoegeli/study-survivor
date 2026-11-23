from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from study_agent.pipeline.pdf_pages import extract_pages, render_pages

SLIDE = landscape(A4)


def make_pdf(path: Path, pages: list[dict], size=SLIDE) -> Path:
    """Jede Seite: lines (Text), image (grosses Bild), rects (Anzahl kleiner Vektor-Rechtecke)."""
    c = canvas.Canvas(str(path), pagesize=size)
    width, height = size
    for number, spec in enumerate(pages, start=1):
        y = height - 60
        for line in spec.get("lines", []):
            c.drawString(40, y, line)
            y -= 20
        c.drawString(40, 20, spec.get("footer", f"Deep Learning, HS 2026   www.fhnw.ch/wirtschaft   {number}"))
        for k in range(spec.get("rects", 0)):
            c.rect(40 + (k % 20) * 10, 100 + (k // 20) * 10, 5, 5)
        if spec.get("image"):
            c.drawImage(ImageReader(Image.new("RGB", (10, 10), "red")), 300, 100, width=400, height=300)
        c.showPage()
    c.save()
    return path


def deck(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "W03.pdf", [
        {"lines": ["Faltungen (Convolutions)", "Stride: Schrittweite des Filters"]},
        {"lines": ["Pooling-Schichten"], "image": True},
        {"lines": ["Netzarchitektur"], "rects": 60},
        {"lines": ["Training", "Loss und Optimierer"]},
        {"lines": ["Zusammenfassung", "2 3"], "footer": "www.fhnw.ch/wirtschaft"},  # Variante auf Kapitelfolien
    ])


def test_text_per_page_title_and_footer_removed(tmp_path):
    pages = extract_pages(deck(tmp_path))
    assert [p.number for p in pages] == [1, 2, 3, 4, 5]
    assert pages[0].title == "Faltungen (Convolutions)"
    assert pages[0].text == "Faltungen (Convolutions)\nStride: Schrittweite des Filters"
    assert all("fhnw.ch" not in p.text for p in pages)
    assert pages[4].title == "Zusammenfassung"
    assert pages[4].text.endswith("2 3")  # Zahlenzeilen (Tabellenwerte) bleiben erhalten
    assert all(p.landscape for p in pages)


def test_visual_pages_by_image_area_or_extra_vectors(tmp_path):
    pages = extract_pages(deck(tmp_path))
    assert [p.visual for p in pages] == [False, True, True, False, False]
    assert pages[1].image_ratio >= 0.15
    assert pages[2].vectors == 60


def test_footer_kept_for_short_documents_and_portrait_detected(tmp_path):
    pages = extract_pages(make_pdf(tmp_path / "kurz.pdf", [{"lines": ["A"]}, {"lines": ["B"]}], size=A4))
    assert "fhnw.ch" in pages[0].text
    assert not pages[0].landscape


def test_render_pages_has_headings_and_markers(tmp_path):
    md = render_pages(extract_pages(deck(tmp_path)))
    assert md.startswith("## Seite 1 · Faltungen (Convolutions)\n<!-- seite: 1 -->\nFaltungen (Convolutions)\n")
    assert "## Seite 2 · Pooling-Schichten\n<!-- seite: 2 · visuell -->" in md
    assert md.count("## Seite ") == 5
