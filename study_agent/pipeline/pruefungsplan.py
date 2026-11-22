"""Prüfungsplan (Excel der Hochschule) lesen und den eigenen Modulen zuordnen.

Der Plan enthält alle Prüfungen aller Studiengänge. Gelesen werden Datum, Zeit,
Dauer, Modul, Anlass-Nr., Dozierende, Studiengang und Klasse; die Spalten werden
über die Kopfzeile erkannt, nicht über feste Positionen.
"""
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

_DATUM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_ZEIT = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–]\s*(\d{1,2})[.:](\d{2})")
_KLAMMER = re.compile(r"\([^)]*\)")
_WORT = re.compile(r"[a-zäöüß]+")
# Wörter, die nichts über das Fach sagen (Kursnamen in Moodle tragen Semester und Studiengang)
_FUELL = frozenset({"bai", "modul", "hs", "fs", "mündlich", "schriftlich", "und", "für", "die", "der", "des", "in",
                    "h", "teil", "einteilung", "gemäss"})

# Kopfzeilen-Erkennung: Spaltenname → Wortanfang in der Kopfzelle (erste Zeile, klein)
_SPALTEN = {
    "datum": ("tag", "datum"),
    "zeit": ("zeit",),
    "dauer": ("dauer",),
    "anlass": ("anlass",),
    "modul": ("modul",),
    "dozierende": ("verantwortlich", "dozierend"),
    "studiengang": ("studiengang",),
    "klasse": ("modell", "klasse"),
}


@dataclass(frozen=True)
class Pruefung:
    index: int
    datum: date
    von: str | None  # "09:00"
    bis: str | None
    dauer: int | None  # Minuten; fehlt bei mündlichen Prüfungen über den ganzen Tag
    modul: str
    anlass: str
    dozierende: str
    studiengang: str
    klasse: str

    def als_dict(self) -> dict:
        d = asdict(self)
        d["datum"] = self.datum.isoformat()
        return d

    def titel(self) -> str:
        zeit = f"{self.von.replace(':', '.')}–{self.bis.replace(':', '.')} Uhr" if self.von and self.bis else ""
        zusatz = ", ".join(x for x in (zeit, f"{self.dauer} Min." if self.dauer else "") if x)
        return f"Prüfung: {self.modul}" + (f" ({zusatz})" if zusatz else "")

    def termin(self, quelle: str) -> dict:
        """Eintrag für termine/<Kurs>.yaml. Ohne Dauer ist es ein Zeitfenster: ganztägig."""
        t = {"datum": self.datum.isoformat(), "titel": self.titel(), "art": "pruefung",
             "quelle": f"{quelle}, Anlass {self.anlass}" if self.anlass else quelle}
        if self.von and self.dauer:
            t["zeit"] = self.von
        return t


def _text(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def _kopf(zeile: tuple) -> dict[str, int] | None:
    spalten: dict[str, int] = {}
    for i, zelle in enumerate(zeile):
        erste = _text(zelle).casefold()
        for name, anfaenge in _SPALTEN.items():
            if name not in spalten and erste.startswith(anfaenge):
                spalten[name] = i
                break
    return spalten if {"datum", "modul"} <= spalten.keys() else None


def lesen(pfad: Path) -> list[Pruefung]:
    """Alle Prüfungen aus allen Blättern. ValueError, wenn keine Kopfzeile mit Datum und Modul gefunden wird."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    except Exception as exc:  # beschädigte oder falsche Datei
        raise ValueError(f"{pfad.name}: keine lesbare Excel-Datei ({type(exc).__name__})") from exc
    out: list[Pruefung] = []
    gefunden = False
    try:
        for ws in wb.worksheets:
            spalten = None
            for zeile in ws.iter_rows(values_only=True):
                if spalten is None:
                    spalten = _kopf(zeile)
                    gefunden = gefunden or spalten is not None
                    continue
                wert = lambda name: zeile[spalten[name]] if name in spalten and spalten[name] < len(zeile) else None
                roh_datum = wert("datum")
                if isinstance(roh_datum, date):
                    tag = roh_datum if type(roh_datum) is date else roh_datum.date()
                elif m := _DATUM.search(_text(roh_datum)):
                    tag = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                else:
                    continue
                modul = _text(wert("modul"))
                if not modul:
                    continue
                z = _ZEIT.search(_text(wert("zeit")))
                dauer = wert("dauer")
                out.append(Pruefung(
                    index=len(out), datum=tag,
                    von=f"{int(z.group(1)):02d}:{z.group(2)}" if z else None,
                    bis=f"{int(z.group(3)):02d}:{z.group(4)}" if z else None,
                    dauer=int(dauer) if isinstance(dauer, (int, float)) and dauer > 0 else None,
                    modul=modul, anlass=_text(wert("anlass")), dozierende=_text(wert("dozierende")).rstrip(";"),
                    studiengang=_text(wert("studiengang")).upper(), klasse=_text(wert("klasse")),
                ))
    finally:
        wb.close()
    if not gefunden:
        raise ValueError(f"{pfad.name}: keine Kopfzeile mit Datum und Modul gefunden")
    return out


def _kern(name: str) -> frozenset[str]:
    """Fachwörter eines Modul- oder Kursnamens, ohne Klammern, Semester, Studiengang."""
    text = _KLAMMER.sub(" ", name.casefold())
    return frozenset(w for w in _WORT.findall(text) if w not in _FUELL and len(w) > 1)


def passendes_modul(pruefung_modul: str, module: list[str]) -> str | None:
    """Modul, dessen Fachwörter mit dem Prüfungsnamen übereinstimmen (eine Seite enthält die andere)."""
    kern = _kern(pruefung_modul)
    if not kern:
        return None
    treffer = []
    for m in module:
        mk = _kern(m)
        if mk and (mk <= kern or kern <= mk) and len(mk & kern) >= min(2, len(kern)):
            treffer.append((len(mk & kern), m))
    return max(treffer)[1] if treffer else None


def vorschlag(pruefungen: list[Pruefung], module: list[str]) -> dict:
    """Ordnet Prüfungen Modulen zu und schätzt den Studiengang aus den Treffern."""
    zuordnung = {p.index: passendes_modul(p.modul, module) for p in pruefungen}
    gaenge = [p.studiengang for p in pruefungen if zuordnung[p.index]]
    studiengang = max(set(gaenge), key=gaenge.count) if gaenge else None
    if studiengang:  # gleiche Modulnamen gibt es in mehreren Studiengängen
        zuordnung = {i: m if m and pruefungen[i].studiengang == studiengang else None for i, m in zuordnung.items()}
    return {"zuordnung": zuordnung, "studiengang": studiengang}
