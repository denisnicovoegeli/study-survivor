"""Dokumente, die der Agent nicht nutzen darf (Häkchen «Nutzen» in der Quellen-Ansicht des Dashboards).

Liste relativer Pfade ab dem moodle-dl-Ordner (wie in knowledge/.manifest.json) in
state/ausgeschlossen.json. Ausgeschlossene Dateien fehlen im Suchindex (Volltext und
semantisch), in den MCP-Tools des Chats und in der Verarbeitung. Heruntergeladen und
ausgelesen werden sie weiterhin, damit das Häkchen jederzeit zurückgesetzt werden kann.
"""
import json
from pathlib import Path

DATEI = "ausgeschlossen.json"


def pfad(state_dir: Path) -> Path:
    return state_dir / DATEI


def laden(state_dir: Path) -> set[str]:
    try:
        daten = json.loads(pfad(state_dir).read_text())
    except (OSError, ValueError):
        return set()
    return {str(x) for x in daten} if isinstance(daten, list) else set()


def setzen(state_dir: Path, rels: list[str], nutzen: bool) -> set[str]:
    """Nimmt Dateien aus der Liste (nutzen=True) oder fügt sie hinzu. Schreibt atomar."""
    for rel in rels:
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise ValueError(f"Ungültiger Pfad: {rel!r}")
    aus = laden(state_dir)
    aus = aus - set(rels) if nutzen else aus | set(rels)
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = pfad(state_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(aus), ensure_ascii=False, indent=1))
    tmp.replace(pfad(state_dir))
    return aus
