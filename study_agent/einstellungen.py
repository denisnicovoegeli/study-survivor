"""Persönliche Einstellungen des Agenten in state/einstellungen.yaml.

Eine Datei für Dashboard, CLI und daily.sh. Fehlt sie, gelten die Standardwerte.
Kommandozeilen-Optionen und Umgebungsvariablen gehen weiterhin vor.
"""
import copy
import re
from pathlib import Path

import yaml

DATEI = "einstellungen.yaml"
TAGE = ("mo", "di", "mi", "do", "fr", "sa", "so")

DEFAULTS: dict = {
    "profil": {"name": ""},
    # aus, bis er im Dashboard oder mit `study zeitplan ein` eingeschaltet wird
    "zeitplan": {"aktiv": False, "zeit": "08:00", "tage": list(TAGE)},
    # ocr_pro_lauf: gescannte PDFs pro Lauf, die das Vision-Modell liest (kostet Tokens, 0 = aus)
    "verarbeitung": {"dateien_pro_lauf": 3, "rag_max": 600, "ocr_pro_lauf": 1},
    "filter": {
        "kurse_ignorieren": [],
        # Unklare Dateien bis zu dieser Grösse sind leere Moodle-Platzhalter
        "leere_seiten_bytes": 50,
        # Unklare Dateien mit diesen Namensteilen sind Moodle-Hilfsseiten
        "namen_ueberspringen": ["Forum intro", "Section summary"],
    },
    # Mitteilungen nach dem täglichen Lauf. ntfy nur, wenn ein Thema gesetzt ist.
    "benachrichtigungen": {
        "mac": True,
        "ntfy_thema": "",
        "ntfy_server": "https://ntfy.sh",
        "neues_material": True,
        "fristen": True,
        "freigaben": True,
        "frist_tage": 3,
    },
    # Archivierte Module: bleiben lesbar, der Agent verarbeitet sie nicht mehr
    "semester": {"archiv": []},
}

_ZEIT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_THEMA = re.compile(r"^[A-Za-z0-9_-]{0,64}$")
_SERVER = re.compile(r"^(https://[^\s/]+|http://(localhost|127\.0\.0\.1)(:\d+)?)(/[^\s]*)?$")


def pfad(state_dir: Path) -> Path:
    return state_dir / DATEI


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if key not in out:
            continue  # unbekannte Schlüssel ignorieren
        if isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _str_liste(value, feld: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{feld}: Liste von Texten erwartet")
    return [v.strip() for v in value if v.strip()]


def _ganzzahl(value, feld: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{feld}: ganze Zahl zwischen {lo} und {hi} erwartet")
    return value


def validieren(daten: dict) -> dict:
    """Ergänzt fehlende Werte mit Standardwerten und prüft Typen. ValueError bei ungültigen Werten."""
    if not isinstance(daten, dict):
        raise ValueError("Einstellungen: Objekt erwartet")
    e = _merge(DEFAULTS, daten)
    name = e["profil"]["name"]
    if not isinstance(name, str) or len(name) > 80:
        raise ValueError("profil.name: Text mit höchstens 80 Zeichen erwartet")
    e["profil"]["name"] = name.strip()

    z = e["zeitplan"]
    if not isinstance(z["aktiv"], bool):
        raise ValueError("zeitplan.aktiv: true oder false erwartet")
    if not isinstance(z["zeit"], str) or not _ZEIT.match(z["zeit"]):
        raise ValueError("zeitplan.zeit: Uhrzeit im Format HH:MM erwartet")
    tage = _str_liste(z["tage"], "zeitplan.tage")
    if any(t not in TAGE for t in tage):
        raise ValueError(f"zeitplan.tage: nur {', '.join(TAGE)} erlaubt")
    z["tage"] = [t for t in TAGE if t in tage]  # Reihenfolge Mo bis So, ohne Doppelte
    if z["aktiv"] and not z["tage"]:
        raise ValueError("zeitplan.tage: mindestens ein Wochentag, oder den Zeitplan ausschalten")

    v = e["verarbeitung"]
    v["dateien_pro_lauf"] = _ganzzahl(v["dateien_pro_lauf"], "verarbeitung.dateien_pro_lauf", 0, 100)
    v["rag_max"] = _ganzzahl(v["rag_max"], "verarbeitung.rag_max", 0, 100000)
    v["ocr_pro_lauf"] = _ganzzahl(v["ocr_pro_lauf"], "verarbeitung.ocr_pro_lauf", 0, 10)

    f = e["filter"]
    f["kurse_ignorieren"] = _str_liste(f["kurse_ignorieren"], "filter.kurse_ignorieren")
    f["leere_seiten_bytes"] = _ganzzahl(f["leere_seiten_bytes"], "filter.leere_seiten_bytes", 0, 100000)
    f["namen_ueberspringen"] = _str_liste(f["namen_ueberspringen"], "filter.namen_ueberspringen")

    b = e["benachrichtigungen"]
    for k in ("mac", "neues_material", "fristen", "freigaben"):
        if not isinstance(b[k], bool):
            raise ValueError(f"benachrichtigungen.{k}: true oder false erwartet")
    thema = b["ntfy_thema"]
    if not isinstance(thema, str) or not _THEMA.match(thema.strip()):
        raise ValueError("benachrichtigungen.ntfy_thema: nur Buchstaben, Ziffern, - und _ (höchstens 64)")
    b["ntfy_thema"] = thema.strip()
    server = b["ntfy_server"]
    if not isinstance(server, str) or not _SERVER.match(server.strip().rstrip("/")):
        raise ValueError("benachrichtigungen.ntfy_server: https-Adresse erwartet")
    b["ntfy_server"] = server.strip().rstrip("/")
    b["frist_tage"] = _ganzzahl(b["frist_tage"], "benachrichtigungen.frist_tage", 1, 30)

    e["semester"]["archiv"] = sorted(set(_str_liste(e["semester"]["archiv"], "semester.archiv")))
    return e


def laden(state_dir: Path) -> dict:
    """Liest die Einstellungen. Fehlende oder kaputte Datei: Standardwerte."""
    p = pfad(state_dir)
    try:
        roh = yaml.safe_load(p.read_text()) if p.exists() else {}
        return validieren(roh or {})
    except (OSError, yaml.YAMLError, ValueError):
        return copy.deepcopy(DEFAULTS)


def speichern(state_dir: Path, daten: dict) -> dict:
    """Prüft und schreibt die Einstellungen atomar. Liefert die gespeicherte Fassung."""
    e = validieren(daten)
    state_dir.mkdir(parents=True, exist_ok=True)
    p = pfad(state_dir)
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(e, allow_unicode=True, sort_keys=False))
    tmp.replace(p)
    return e


def wert(e: dict, schluessel: str):
    """Liest einen Wert mit Punkt-Pfad, z. B. „verarbeitung.dateien_pro_lauf“. KeyError, wenn unbekannt."""
    cur = e
    for teil in schluessel.split("."):
        if not isinstance(cur, dict) or teil not in cur:
            raise KeyError(schluessel)
        cur = cur[teil]
    return cur


def ueberspringen_grund(filt: dict, course: str, name: str, source: Path, route: str | None) -> str | None:
    """Grund, warum der Agent eine Datei automatisch auslässt, sonst None.

    Ignorierte Kurse gelten für alle Dateien. Die übrigen Regeln greifen nur bei
    unklaren Dateien (Route „fragen“), damit echtes Material nie still verschwindet.
    """
    if course in filt.get("kurse_ignorieren", []):
        return "Kurs ignoriert"
    if course in filt.get("archiv", []):
        return "Modul archiviert"
    if route != "fragen":
        return None
    low = name.casefold()
    if any(teil.casefold() in low for teil in filt.get("namen_ueberspringen", [])):
        return "Moodle-Hilfsseite"
    grenze = filt.get("leere_seiten_bytes", 0)
    if grenze:
        try:
            if source.stat().st_size <= grenze:
                return "leere Seite"
        except OSError:
            pass
    return None
