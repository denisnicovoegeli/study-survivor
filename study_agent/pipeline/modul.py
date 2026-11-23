"""Parser und Modell für lernen/<Kurs>/modul.md.

Liest und schreibt Modul-Informationen (Leistungsnachweis, Gewichtung, Dauer,
Hilfsmittel, Termine, Quellen sowie Prüfungs- und Projektdetails).
Nutzt ruamel.yaml, damit der Code sowohl im CLI als auch im Hermes-Plugin
(ohne PyYAML) läuft.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ruamel.yaml import YAML

LEISTUNGSNACHWEIS_WERTE = frozenset({"pruefung", "projekt", "beides"})


@dataclass
class ModulInfo:
    leistungsnachweis: Optional[str] = None  # pruefung, projekt, beides oder None
    gewichtung: Optional[str] = None
    dauer: Optional[str] = None
    hilfsmittel: Optional[str] = None
    daten: List[str] = field(default_factory=list)
    quellen: List[str] = field(default_factory=list)
    pruefung_items: Dict[str, List[str]] = field(default_factory=dict)  # datei -> items
    projekt_items: Dict[str, List[str]] = field(default_factory=dict)   # datei -> items
    has_modul_file: bool = True
    legacy_pruefung_text: Optional[str] = None
    legacy_projekt_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialisierbares Wörterbuch für APIs."""
        return {
            "leistungsnachweis": self.leistungsnachweis,
            "gewichtung": self.gewichtung,
            "dauer": self.dauer,
            "hilfsmittel": self.hilfsmittel,
            "daten": list(self.daten),
            "quellen": list(self.quellen),
            "pruefung": self.pruefung_items,
            "projekt": self.projekt_items,
            "has_modul_file": self.has_modul_file,
            "legacy_pruefung": self.legacy_pruefung_text,
            "legacy_projekt": self.legacy_projekt_text,
        }


def _yaml_instance() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_CH_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _norm_leistungsnachweis(value: Any) -> Optional[str]:
    if value is None:
        return None
    norm = str(value).lower().replace("ü", "ue").strip()
    return norm if norm in LEISTUNGSNACHWEIS_WERTE else None


def kombiniere_leistungsnachweis(alt: Optional[str], neu: Optional[str]) -> Optional[str]:
    """Prüfung und Projekt aus verschiedenen Quellen ergeben «beides», nie wird ein Teil überschrieben."""
    if not alt or alt == neu:
        return neu or alt
    if not neu:
        return alt
    return "beides"


def _leistungsnachweis_aus_gewichtung(gewichtung: Optional[str]) -> Optional[str]:
    g = (gewichtung or "").lower().replace("ü", "ue")
    if "pruef" in g and "projekt" in g:
        return "beides"
    return None


def _datum_eintrag(text: str) -> tuple[Optional[str], str]:
    """Zerlegt einen Termin-Eintrag in ISO-Datum und Text."""
    m = _ISO_RE.search(text) or _CH_RE.search(text)
    if not m:
        return None, text.strip()
    if m.re is _ISO_RE:
        iso = m.group(0)
    else:
        iso = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    rest = (text[: m.start()] + text[m.end():]).strip().lstrip(":–-").strip()
    return iso, rest


def _vergleichstext(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", text)).strip().lower()


def normalisiere_daten(daten: List[str]) -> List[str]:
    """Einheitlich «YYYY-MM-DD Text», Doppelte entfernt, nach Datum sortiert.

    Gleiches Datum mit gleichem Textanfang (ohne Klammerzusätze) oder ohne Text gilt als doppelt;
    die ausführlichere Fassung bleibt.
    """
    pro_datum: Dict[str, List[str]] = {}
    ohne_datum: List[str] = []
    for eintrag in daten:
        iso, rest = _datum_eintrag(str(eintrag))
        if iso is None:
            if rest and rest not in ohne_datum:
                ohne_datum.append(rest)
            continue
        liste = pro_datum.setdefault(iso, [])
        key = _vergleichstext(rest)
        for i, vorhanden in enumerate(liste):
            vkey = _vergleichstext(vorhanden)
            if key == vkey or not key or (vkey and (key.startswith(vkey) or vkey.startswith(key))):
                if len(rest) > len(vorhanden):
                    liste[i] = rest
                break
        else:
            liste.append(rest)
    out: List[str] = []
    for iso in sorted(pro_datum):
        texte = [t for t in pro_datum[iso] if t] or [""]
        out.extend(f"{iso} {t}".strip() for t in texte)
    return out + ohne_datum


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+([^\n]+)", re.M)
_SUBSECTION_RE = re.compile(r"^###\s+([^\n]+)", re.M)


def parse_modul_markdown(text: str) -> ModulInfo:
    """Parst den Inhalt einer modul.md in ein ModulInfo-Objekt."""
    info = ModulInfo(has_modul_file=True)
    body = text

    match = _FRONTMATTER_RE.match(text)
    if match:
        fm_text = match.group(1)
        body = text[match.end():]
        yaml = _yaml_instance()
        data = yaml.load(fm_text) or {}
        if isinstance(data, dict):
            ln = data.get("leistungsnachweis")
            if ln in LEISTUNGSNACHWEIS_WERTE:
                info.leistungsnachweis = str(ln)
            elif ln is not None and str(ln).strip():
                # Normalisierung falls Prüfung mit Umlaut etc.
                norm = str(ln).lower().replace("ü", "ue").strip()
                if norm in LEISTUNGSNACHWEIS_WERTE:
                    info.leistungsnachweis = norm

            if data.get("gewichtung") is not None:
                info.gewichtung = str(data["gewichtung"]).strip() or None
            if data.get("dauer") is not None:
                info.dauer = str(data["dauer"]).strip() or None
            if data.get("hilfsmittel") is not None:
                info.hilfsmittel = str(data["hilfsmittel"]).strip() or None

            daten = data.get("daten")
            if isinstance(daten, list):
                info.daten = [str(d).strip() for d in daten if str(d).strip()]
            elif isinstance(daten, str) and daten.strip():
                info.daten = [daten.strip()]

            quellen = data.get("quellen")
            if isinstance(quellen, list):
                info.quellen = [str(q).strip() for q in quellen if str(q).strip()]
            elif isinstance(quellen, str) and quellen.strip():
                info.quellen = [quellen.strip()]

    # Abschnitte im Body parsen: ## Prüfung, ## Projekt
    sections = _parse_top_sections(body)
    if "Prüfung" in sections or "Pruefung" in sections:
        sec_text = sections.get("Prüfung") or sections.get("Pruefung") or ""
        info.pruefung_items = _parse_file_items(sec_text)
    if "Projekt" in sections:
        sec_text = sections.get("Projekt") or ""
        info.projekt_items = _parse_file_items(sec_text)

    return info


def _parse_top_sections(text: str) -> Dict[str, str]:
    """Trennt Markdown nach ## Überschriften auf."""
    matches = list(_SECTION_RE.finditer(text))
    out: Dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[title] = text[start:end].strip()
    return out


def _parse_file_items(section_text: str) -> Dict[str, List[str]]:
    """Trennt Unterabschnitte nach ### <Datei> oder liest einfache Listenpunkte ein."""
    sub_matches = list(_SUBSECTION_RE.finditer(section_text))
    out: Dict[str, List[str]] = {}
    if sub_matches:
        for i, m in enumerate(sub_matches):
            fname = m.group(1).strip()
            start = m.end()
            end = sub_matches[i + 1].start() if i + 1 < len(sub_matches) else len(section_text)
            chunk = section_text[start:end].strip()
            items = [line[1:].strip() for line in chunk.splitlines() if line.strip().startswith("- ")]
            if items:
                out[fname] = items
    else:
        # Falls direkt Listenpunkte ohne ### Datei vorhanden sind
        items = [line[1:].strip() for line in section_text.splitlines() if line.strip().startswith("- ")]
        if items:
            out["Allgemein"] = items
    return out


def render_modul_markdown(info: ModulInfo, course_name: Optional[str] = None) -> str:
    """Erzeugt den Inhalt von modul.md als String."""
    fm_dict: Dict[str, Any] = {
        "leistungsnachweis": info.leistungsnachweis,
        "gewichtung": info.gewichtung,
        "dauer": info.dauer,
        "hilfsmittel": info.hilfsmittel,
        "daten": list(info.daten),
        "quellen": list(info.quellen),
    }

    yaml = _yaml_instance()
    buf = io.StringIO()
    yaml.dump(fm_dict, buf)
    fm_str = buf.getvalue().strip()

    title = f"# Modulinfo – {course_name}\n\n" if course_name else ""
    lines = ["---", fm_str, "---", "", title.rstrip()]
    if lines[-1]:
        lines.append("")

    lines.append("## Prüfung")
    lines.append("")
    if info.pruefung_items:
        for fname, items in sorted(info.pruefung_items.items()):
            lines.append(f"### {fname}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("*(Keine Prüfungshinweise vorhanden)*")
        lines.append("")

    lines.append("## Projekt")
    lines.append("")
    if info.projekt_items:
        for fname, items in sorted(info.projekt_items.items()):
            lines.append(f"### {fname}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append("*(Keine Projekthinweise vorhanden)*")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def load_modul(course_dir: Path) -> ModulInfo:
    """Liest modul.md oder fällt auf pruefung.md/projekt.md zurück."""
    modul_file = course_dir / "modul.md"
    if modul_file.is_file():
        try:
            return parse_modul_markdown(modul_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fallback auf alte Dateien
    info = ModulInfo(has_modul_file=False)
    p_file = course_dir / "pruefung.md"
    if p_file.is_file():
        try:
            text = p_file.read_text(encoding="utf-8")
            info.legacy_pruefung_text = text
            info.pruefung_items = _parse_legacy_file(text)
        except Exception:
            pass

    proj_file = course_dir / "projekt.md"
    if proj_file.is_file():
        try:
            text = proj_file.read_text(encoding="utf-8")
            info.legacy_projekt_text = text
            info.projekt_items = _parse_legacy_file(text)
        except Exception:
            pass

    return info


def _parse_legacy_file(text: str) -> Dict[str, List[str]]:
    """Parst die alten pruefung.md/projekt.md (## <Datei> gefolgt von - <info>)."""
    matches = list(_SECTION_RE.finditer(text))
    out: Dict[str, List[str]] = {}
    for i, m in enumerate(matches):
        fname = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        items = [line[1:].strip() for line in chunk.splitlines() if line.strip().startswith("- ")]
        if items:
            out[fname] = items
    return out


def merge_modul(
    course_dir: Path,
    source_name: str,
    modul_data: Optional[Dict[str, Any]] = None,
    pruefung_entries: Optional[List[Dict[str, Any]]] = None,
    projekt_entries: Optional[List[Dict[str, Any]]] = None,
) -> ModulInfo:
    """Führt neue Modulinformationen in lernen/<Kurs>/modul.md zusammen.

    - Unbekannte Felder werden nicht geraten, vorhandene Werte bleiben erhalten.
    - Abschnitte für dieselbe Quelldatei werden ersetzt, andere bleiben unberührt.
    - Speichert das Ergebnis atomar in modul.md.
    """
    course_dir.mkdir(parents=True, exist_ok=True)
    current = load_modul(course_dir)

    # Frontmatter-Felder aktualisieren
    if modul_data and isinstance(modul_data, dict):
        current.leistungsnachweis = kombiniere_leistungsnachweis(
            current.leistungsnachweis, _norm_leistungsnachweis(modul_data.get("leistungsnachweis"))
        )

        gew = modul_data.get("gewichtung")
        if gew is not None and str(gew).strip():
            current.gewichtung = str(gew).strip()

        dauer = modul_data.get("dauer")
        if dauer is not None and str(dauer).strip():
            current.dauer = str(dauer).strip()

        hilf = modul_data.get("hilfsmittel")
        if hilf is not None and str(hilf).strip():
            current.hilfsmittel = str(hilf).strip()

        for d in modul_data.get("daten") or []:
            d_str = str(d).strip()
            if d_str and d_str not in current.daten:
                current.daten.append(d_str)

        for q in modul_data.get("quellen") or []:
            q_str = str(q).strip()
            if q_str and q_str not in current.quellen:
                current.quellen.append(q_str)

    # Prüfungsabschnitt für source_name aktualisieren
    if pruefung_entries is not None:
        items = []
        for e in pruefung_entries:
            info = str(e.get("info") or "").strip()
            quelle = str(e.get("quelle") or "").strip()
            if info:
                items.append(f"{info} ({quelle})" if quelle and quelle not in info else info)
        if items:
            current.pruefung_items[source_name] = items
            # Auch bei quellen ergänzen falls noch nicht drin
            for e in pruefung_entries:
                q = str(e.get("quelle") or "").strip()
                if q and q not in current.quellen:
                    current.quellen.append(q)

    # Projektabschnitt für source_name aktualisieren
    if projekt_entries is not None:
        items = []
        for e in projekt_entries:
            info = str(e.get("info") or "").strip()
            quelle = str(e.get("quelle") or "").strip()
            if info:
                items.append(f"{info} ({quelle})" if quelle and quelle not in info else info)
        if items:
            current.projekt_items[source_name] = items
            for e in projekt_entries:
                q = str(e.get("quelle") or "").strip()
                if q and q not in current.quellen:
                    current.quellen.append(q)

    current.daten = normalisiere_daten(current.daten)
    current.leistungsnachweis = kombiniere_leistungsnachweis(
        current.leistungsnachweis, _leistungsnachweis_aus_gewichtung(current.gewichtung)
    )

    current.has_modul_file = True
    rendered = render_modul_markdown(current, course_name=course_dir.name)
    modul_file = course_dir / "modul.md"
    modul_file.write_text(rendered, encoding="utf-8")
    return current
