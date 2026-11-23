"""Karteikarten aus den Folien-Notizen eines Moduls erstellen.

Quelle sind die .folien.md in knowledge/ (wörtlicher Folientext mit «## Folie N», inklusive
Bildbeschreibungen), sonst der ausgelesene Rohtext. Das Modell schreibt Begriff, Definition und
Folien; die Karten landen als Tabellenzeilen in lernen/<Kurs>/begriffe.md, dem Format, das die
Karteikarten-Ansicht (routes_karten.py) schon liest. Vorhandene Begriffe werden nicht überschrieben,
damit der Leitner-Lernstand (state/karten.json, Schlüssel = Begriff) erhalten bleibt.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from study_agent.config import Settings

BEGRIFFE = "begriffe.md"
KOPF = "| Begriff | Definition | Quelle |\n|---|---|---|\n"
MAX_ZEICHEN = 60000      # Text pro Dokument an das Modell (ein Foliensatz hat meist 20–50k)
ANZAHL = (5, 30)         # erlaubter Bereich pro Dokument
_ZELLE = re.compile(r"[|\n\r]+")

PROMPT = """Erstelle Karteikarten zum Lernen für die Prüfung aus diesen Unterlagen.

Regeln:
- Genau {anzahl} Karten (oder weniger, wenn die Unterlagen nicht so viele prüfungsrelevante Begriffe hergeben).
- Vorderseite: ein Fachbegriff, ein Verfahren oder eine kurze Frage (höchstens 8 Wörter).
- Rückseite: Definition oder Antwort in 1–3 Sätzen, nur mit Inhalten aus den Unterlagen.
- Wähle, was in einer Prüfung gefragt würde: Kernbegriffe, Unterschiede, Formeln in Worten, Abläufe.
  Keine Organisation, keine Termine, keine Namen von Dozierenden.
- folien: Nummern der Folien oder Seiten (aus «## Folie N» bzw. «## Seite N»), auf denen der Inhalt steht.
- Sprache wie die Unterlagen, Schweizer Rechtschreibung (ss statt ß).
{bekannt}
# Unterlagen: {datei}
{text}"""


class Karte(BaseModel):
    begriff: str = Field(description="Vorderseite: Begriff oder kurze Frage")
    definition: str = Field(description="Rückseite: 1–3 Sätze")
    folien: list[int] = Field(default=[], description="Folien- oder Seitennummern")


class Karten(BaseModel):
    karten: list[Karte]


def begriffe_pfad(settings: Settings, kurs: str) -> Path:
    return settings.lernen_dir / kurs / BEGRIFFE


def vorhandene_begriffe(pfad: Path) -> set[str]:
    if not pfad.is_file():
        return set()
    out = set()
    for zeile in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
        teile = [t.strip() for t in zeile.strip().strip("|").split("|")]
        if len(teile) >= 2 and teile[0] and teile[0].lower() != "begriff" and not set(teile[0]) <= {"-", ":"}:
            out.add(teile[0].casefold())
    return out


def _zelle(text: str) -> str:
    return _ZELLE.sub(" ", str(text)).strip()


def quelle_text(datei: str, folien: list[int]) -> str:
    nummern = sorted({int(n) for n in folien if int(n) > 0})
    return f"{datei}, Folie {', '.join(map(str, nummern))}" if nummern else datei


def anhaengen(pfad: Path, datei: str, karten: list[Karte]) -> int:
    """Hängt neue Karten an begriffe.md an. Liefert die Zahl der neuen Karten (Doppelte zählen nicht)."""
    bekannt = vorhandene_begriffe(pfad)
    zeilen = []
    for k in karten:
        begriff, definition = _zelle(k.begriff), _zelle(k.definition)
        if not begriff or not definition or begriff.casefold() in bekannt:
            continue
        bekannt.add(begriff.casefold())
        zeilen.append(f"| {begriff} | {definition} | {_zelle(quelle_text(datei, k.folien))} |\n")
    if not zeilen:
        return 0
    pfad.parent.mkdir(parents=True, exist_ok=True)
    alt = pfad.read_text(encoding="utf-8") if pfad.is_file() else f"# Begriffe\n\n{KOPF}"
    if not alt.endswith("\n"):
        alt += "\n"
    pfad.write_text(alt + "".join(zeilen), encoding="utf-8")
    return len(zeilen)


def dokumente(settings: Settings, kurs: str) -> list[dict[str, Any]]:
    """Dokumente eines Moduls, aus denen Karten entstehen können: ausgelesen, genutzt, Lernstoff zuerst."""
    from study_agent.pipeline.quellen import quellen_modul

    q = quellen_modul(settings, kurs)
    karten_pro_datei: dict[str, int] = {}
    pfad = begriffe_pfad(settings, kurs)
    if pfad.is_file():
        for zeile in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
            teile = [t.strip() for t in zeile.strip().strip("|").split("|")]
            if len(teile) >= 3:
                datei = teile[2].split(",")[0].strip()
                karten_pro_datei[datei] = karten_pro_datei.get(datei, 0) + 1
    out = []
    for a in q["abschnitte"]:
        for d in a["dateien"]:
            if d["art"] not in ("Datei", "Eigene Datei") or d["status"] != "nutzt":
                continue
            out.append({
                "rel": d["rel"], "titel": d["titel"], "abschnitt": a["name"], "klasse": d["klasse"],
                "folien": d["folien_aufbereitet"], "karten": karten_pro_datei.get(Path(d["rel"]).name, 0),
                "lernstoff": d["klasse"] == "Folien",
            })
    return out


def text_fuer(settings: Settings, rel: str) -> str:
    from study_agent.pipeline.convert import folien_path, knowledge_path

    for p in (folien_path(settings.knowledge_dir, Path(rel)), knowledge_path(settings.knowledge_dir, Path(rel))):
        if p.is_file():
            text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8", errors="replace"), flags=re.S)
            return text.strip()[:MAX_ZEICHEN]
    raise ValueError(f"{rel}: kein ausgelesener Text")


def erstellen(settings: Settings, kurs: str, rels: list[str], anzahl: int = 10,
              modell: Callable[[str], Karten] | None = None,
              fortschritt: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    """Erstellt Karten für jedes Dokument. Fehler bei einem Dokument stoppen die übrigen nicht."""
    from study_agent.pipeline.ausschluss import laden as laden_ausschluss

    anzahl = max(ANZAHL[0], min(ANZAHL[1], int(anzahl)))
    if modell is None:
        from study_agent.llm import MAIN_MODEL, chat_model
        llm = chat_model(MAIN_MODEL).with_structured_output(Karten, method="json_schema")
        modell = lambda prompt: llm.invoke(prompt)  # noqa: E731
    aus = laden_ausschluss(settings.state_dir)
    pfad = begriffe_pfad(settings, kurs)
    neu, fehler = 0, []
    for i, rel in enumerate(rels):
        datei = Path(rel).name
        if fortschritt:
            fortschritt(i, datei)
        if rel in aus or not rel.split("/")[0] in (kurs, "_eigene"):
            fehler.append(f"{datei}: nicht in diesem Modul oder abgewählt")
            continue
        try:
            bekannt = sorted(vorhandene_begriffe(pfad))[:150]
            hinweis = ("- Diese Begriffe gibt es schon, wähle andere: " + "; ".join(bekannt) + "\n") if bekannt else ""
            ergebnis = modell(PROMPT.format(anzahl=anzahl, bekannt=hinweis, datei=datei, text=text_fuer(settings, rel)))
            neu += anhaengen(pfad, datei, ergebnis.karten[:anzahl])
        except Exception as exc:  # noqa: BLE001 ein kaputtes Dokument stoppt die anderen nicht
            fehler.append(f"{datei}: {type(exc).__name__}: {exc}"[:200])
    return {"neu": neu, "fehler": fehler}
