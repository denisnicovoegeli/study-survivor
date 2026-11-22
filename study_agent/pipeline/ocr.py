"""Texterkennung für gescannte PDFs über das Vision-Modell.

pdfplumber findet in eingescannten Folien keinen Text. Diese Seiten werden als Bild
gerendert und in kleinen Gruppen an das Vision-Modell geschickt, das den Text
wörtlich abschreibt. Das Ergebnis sind PageInfo-Einträge wie bei normalen PDFs,
die Umwandlung läuft danach unverändert weiter.
"""
import base64
import io
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from study_agent.pipeline.pdf_pages import PageInfo

SCALE = 1.6  # ca. 115 dpi: genug für Folientext, kleinere Bilder als in verarbeiten
GRUPPE = 4  # Seiten pro Anfrage
MAX_SEITEN = 80  # längere Scans werden nicht automatisch gelesen
_SEITE = re.compile(r"^=== Seite (\d+) ===\s*$", re.M)

PROMPT = (
    "Du bekommst eingescannte Seiten aus Unterrichtsmaterial. Schreibe den sichtbaren Text jeder Seite "
    "wörtlich ab, in der Originalsprache, ohne Zusammenfassung und ohne Kommentar. Behalte Aufzählungen "
    "und Tabellen als Markdown bei. Beschreibe Diagramme oder Bilder ohne Text in einem kurzen Satz in "
    "eckigen Klammern. Beginne jede Seite mit einer eigenen Zeile «=== Seite N ===» (N wie angegeben). "
    "Ist eine Seite leer, schreibe nur die Kopfzeile."
)

Transkribierer = Callable[[list[tuple[int, bytes]]], str]


def seiten_bilder(path: Path, scale: float = SCALE) -> list[tuple[int, bytes, bool]]:
    """(Seitennummer, PNG, quer) pro Seite."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        if len(doc) > MAX_SEITEN:
            raise ValueError(f"{len(doc)} Seiten, mehr als {MAX_SEITEN} werden nicht automatisch gelesen")
        out = []
        for i in range(len(doc)):
            seite = doc[i]
            breite, hoehe = seite.get_size()
            buf = io.BytesIO()
            seite.render(scale=scale).to_pil().convert("L").save(buf, format="PNG", optimize=True)
            out.append((i + 1, buf.getvalue(), breite > hoehe))
        return out
    finally:
        doc.close()


def vision_transkribierer(model: str | None = None) -> Transkribierer:
    from langchain_core.messages import HumanMessage

    from study_agent.llm import VISION_MODEL, chat_model

    llm = chat_model(model or VISION_MODEL)

    def run(bilder: list[tuple[int, bytes]]) -> str:
        parts: list[dict] = [{"type": "text", "text": PROMPT}]
        for nr, png in bilder:
            parts.append({"type": "text", "text": f"Seite {nr}:"})
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}})
        antwort = llm.invoke([HumanMessage(content=parts)])
        return antwort.content if isinstance(antwort.content, str) else str(antwort.content)

    return run


def zerlegen(text: str, erwartet: list[int]) -> dict[int, str]:
    """Antwort des Modells in Seiten aufteilen. Fehlen die Kopfzeilen, geht alles an die erste Seite."""
    teile = _SEITE.split(text)
    if len(teile) < 3:
        return {erwartet[0]: text.strip()} if erwartet else {}
    out: dict[int, str] = {}
    for i in range(1, len(teile) - 1, 2):
        nr = int(teile[i])
        if nr in erwartet:
            out[nr] = (out.get(nr, "") + "\n" + teile[i + 1]).strip()
    return out


def ocr_pages(path: Path, transkribieren: Transkribierer, bilder: list[tuple[int, bytes, bool]] | None = None
              ) -> list[PageInfo]:
    """Alle Seiten eines gescannten PDFs als PageInfo. Jede Seite gilt als visuell (es ist ein Bild)."""
    bilder = seiten_bilder(path) if bilder is None else bilder
    texte: dict[int, str] = {}
    for start in range(0, len(bilder), GRUPPE):
        gruppe = bilder[start:start + GRUPPE]
        texte.update(zerlegen(transkribieren([(nr, png) for nr, png, _ in gruppe]), [nr for nr, *_ in gruppe]))
    # Titel: erste Zeile, die nicht auf fast jeder Seite steht (Logo, Kopfzeile der Vorlage)
    zeilen = {nr: [z.strip(" #*") for z in texte.get(nr, "").splitlines() if z.strip(" #*")] for nr, *_ in bilder}
    zaehler = Counter(z for zs in zeilen.values() for z in set(zs))
    vorlage = {z for z, n in zaehler.items() if len(bilder) >= 4 and n > len(bilder) / 2}
    pages = []
    for nr, _, quer in bilder:
        text = texte.get(nr, "").strip()
        titel = next((z for z in zeilen[nr] if z not in vorlage and len(z) >= 3 and not z.startswith("[")), "")
        pages.append(PageInfo(number=nr, title=titel[:80], text=text, landscape=quer,
                              image_ratio=1.0, vectors=0, visual=True))
    return pages
