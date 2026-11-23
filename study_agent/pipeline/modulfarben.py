"""Farben der Module (Punkte im Kalender, in Lernen, in der Suche).

state/modulfarben.json hält pro Modul eine Hex-Farbe. Ein Modul ohne Farbe bekommt beim ersten
Abruf die erste noch freie Farbe der Palette, und die wird gespeichert. So haben zwei Module nie
dieselbe Standardfarbe, und ein neues Modul verschiebt die Farben der anderen nicht.
"""
import colorsys
import json
import re
from pathlib import Path

DATEI = "modulfarben.json"
# Gut unterscheidbar, auf hellem und dunklem Hintergrund lesbar
PALETTE = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#a855f7",
           "#14b8a6", "#ec4899", "#f97316", "#84cc16", "#6366f1"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def pfad(state_dir: Path) -> Path:
    return state_dir / DATEI


def laden(state_dir: Path) -> dict[str, str]:
    try:
        daten = json.loads(pfad(state_dir).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v).lower() for k, v in daten.items() if _HEX.match(str(v))} if isinstance(daten, dict) else {}


def _speichern(state_dir: Path, farben: dict[str, str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = pfad(state_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(farben.items())), ensure_ascii=False, indent=1))
    tmp.replace(pfad(state_dir))


def _freie_farbe(belegt: set[str], n: int) -> str:
    for f in PALETTE:
        if f not in belegt:
            return f
    # Palette aufgebraucht: Farbtöne im goldenen Winkel verteilen
    r, g, b = colorsys.hls_to_rgb(((n * 137.508) % 360) / 360, 0.55, 0.65)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def farben(state_dir: Path, module: list[str]) -> dict[str, str]:
    """Farbe jedes Moduls; fehlende werden mit freien Palettenfarben ergänzt und gespeichert."""
    gespeichert = laden(state_dir)
    belegt = set(gespeichert.values())
    neu = False
    for i, name in enumerate(sorted(module)):
        if name not in gespeichert:
            f = _freie_farbe(belegt, len(belegt) + i)
            gespeichert[name] = f
            belegt.add(f)
            neu = True
    if neu:
        _speichern(state_dir, gespeichert)
    return {name: gespeichert[name] for name in module}


def setzen(state_dir: Path, name: str, farbe: str | None, module: list[str]) -> dict[str, str]:
    """Eigene Farbe setzen. farbe=None setzt auf eine freie Standardfarbe zurück."""
    if name not in module:
        raise ValueError(f"Unbekanntes Modul: {name}")
    gespeichert = laden(state_dir)
    if farbe is None:
        gespeichert.pop(name, None)
        belegt = {f for k, f in gespeichert.items() if k in module}
        gespeichert[name] = _freie_farbe(belegt, len(belegt))
    else:
        if not _HEX.match(farbe or ""):
            raise ValueError("Farbe als #rrggbb angeben")
        gespeichert[name] = farbe.lower()
    _speichern(state_dir, gespeichert)
    return farben(state_dir, module)
