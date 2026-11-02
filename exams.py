import re
from pathlib import Path
import pandas as pd

EXAM_FILE = Path(__file__).parent / "data" / "pruefungsplan_HS26.xlsx"
PROGRAMME = ["BAI"]

def _clean(text) -> str:
    """Zeilenumbrüche und doppelte Leerzeichen entfernen."""
    return re.sub(r"\s+", " ",str(text)).strip()

def load_exams() -> dict[str, list[dict]]:
    """Liest den Prüfungsplan und liefert dieselbe Struktur wie das frühere EXAMS-Dict:
    {modulname_kleingeschrieben: [{datum, wochentag, zeit, dauer_min, form, klasse, dozierende}, ...]}
    """
    df = pd.read_excel(EXAM_FILE)
    # Spaltenköpfe sind zweisprachig und enthalten Zeilenumbrüche -> per Position benennen
    df = df.iloc[:, :8]
    df.columns = ["tag", "zeit", "dauer", "nr", "modul", "dozierende", "studiengang", "klasse"]
 
    df = df.dropna(subset=["tag", "modul"])
    df = df[df["studiengang"].astype(str).str.strip().str.upper().isin(PROGRAMME)]
 
    exams: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        wochentag, datum = [s.strip() for s in str(row["tag"]).split(",", 1)]
        modul = _clean(row["modul"])
        oral = "mündlich" in modul.lower()
        # Zusatz wie "mündlich (Einteilung gemäss Dozentin)" aus dem Modulnamen entfernen
        modul = re.sub(r"\s*mündlich.*$", "", modul, flags=re.IGNORECASE)
        zeit = _clean(row["zeit"]).replace(".", ":")
        dauer = None if pd.isna(row["dauer"]) else int(row["dauer"])
        exams.setdefault(modul.lower(), []).append({
            "datum": datum,
            "wochentag": wochentag,
            "zeit": zeit,
            "dauer_min": dauer,
            "form": "mündlich" if oral else "schriftlich",
            "klasse": _clean(row["klasse"]),
            "dozierende": _clean(row["dozierende"]).replace(":", ";"),
        })
    return exams