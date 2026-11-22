"""Eigener MCP-Server „kursmaterial“ (SW6, FastMCP über stdio).

Gibt nur lesenden Zugriff auf den aufbereiteten Text in data/knowledge
(Rohtext *.md bzw. genauer Folientext *.folien.md). Original-PDFs und
moodle-dl/config.json werden nie geöffnet.

Start zum Testen: uv run python -m study_agent.agent.mcp_server
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from study_agent.config import load_settings
from study_agent.pipeline.moodle_db import current_courses
from study_agent.pipeline.suche import _skip

mcp = FastMCP("kursmaterial", log_level="WARNING")
MAX_CHARS = 12000


def _knowledge() -> Path:
    return load_settings().knowledge_dir


def _kurs_dir(kurs: str) -> Path:
    root = _knowledge()
    treffer = [d for d in root.iterdir() if d.is_dir() and kurs.casefold() in d.name.casefold()]
    if not treffer:
        raise ValueError(f"Kein Kurs passt zu '{kurs}'. Mit kurse_auflisten die Namen prüfen.")
    if len(treffer) > 1:
        raise ValueError("Mehrdeutig, passende Kurse: " + "; ".join(d.name for d in treffer))
    return treffer[0]


@mcp.tool()
def kurse_auflisten() -> list[str]:
    """Listet die Kurse des aktuellen Semesters, zu denen Kursmaterial vorliegt."""
    from datetime import date

    root = _knowledge()
    settings = load_settings()
    try:
        aktuell = {c.name for c in current_courses(settings.moodle_db, date.today())}
    except Exception:
        aktuell = set()
    namen = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))
    return [n for n in namen if not aktuell or n in aktuell]


@mcp.tool()
def dateien_auflisten(kurs: str) -> list[str]:
    """Listet die Unterlagen eines Kurses (relativer Pfad ab Kursordner, ohne .md-Endung).

    Args:
        kurs: Teil des Kursnamens, z. B. "Deep Learning".
    """
    from study_agent.pipeline.ausschluss import laden

    d = _kurs_dir(kurs)
    aus = laden(load_settings().state_dir)
    out = set()
    for p in d.rglob("*.md"):
        rel = p.relative_to(d)
        if p.name == "INDEX.md" or _skip(rel):
            continue
        name = rel.as_posix()
        name = name[:-len(".folien.md")] if name.endswith(".folien.md") else name[:-len(".md")]
        if f"{d.name}/{name}" not in aus and f"_eigene/{d.name}/{name}" not in aus:
            out.add(name)
    return sorted(out)


@mcp.tool()
def datei_lesen(kurs: str, datei: str, ab_zeichen: int = 0) -> str:
    """Liest den Text einer Unterlage (genauer Folientext, falls vorhanden, sonst Rohtext).

    Für Fragen, die eine ganze Datei betreffen (z. B. "fasse SW7 zusammen"). Lange
    Dateien kommen in Teilen von 12000 Zeichen; mit ab_zeichen weiterlesen.

    Args:
        kurs: Teil des Kursnamens.
        datei: Pfad wie von dateien_auflisten geliefert (oder ein eindeutiger Teil davon).
        ab_zeichen: Startposition für lange Dateien.
    """
    d = _kurs_dir(kurs)
    kandidaten = [f for f in dateien_auflisten(d.name) if datei.casefold() in f.casefold()]
    if not kandidaten:
        raise ValueError(f"Keine Datei passt zu '{datei}'.")
    if len(kandidaten) > 1 and datei not in kandidaten:
        raise ValueError("Mehrdeutig: " + "; ".join(kandidaten[:10]))
    rel = datei if datei in kandidaten else kandidaten[0]
    folien = d / f"{rel}.folien.md"
    path = folien if folien.is_file() else d / f"{rel}.md"
    if d.resolve() not in path.resolve().parents:
        raise ValueError("Pfad ausserhalb des Kursordners.")
    text = path.read_text()
    teil = text[ab_zeichen:ab_zeichen + MAX_CHARS]
    rest = len(text) - ab_zeichen - len(teil)
    kopf = f"Quelle: {d.name} / {rel} ({'Folientext' if path == folien else 'Rohtext'})\n\n"
    return kopf + teil + (f"\n\n[... {rest} weitere Zeichen, weiter mit ab_zeichen={ab_zeichen + MAX_CHARS}]" if rest > 0 else "")


if __name__ == "__main__":
    mcp.run(transport="stdio")
