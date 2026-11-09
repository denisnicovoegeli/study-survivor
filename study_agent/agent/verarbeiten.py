"""Graph `verarbeiten` (SW8 Multi-Agent, Vier-Augen-Prinzip wie im Rechnungs-Beispiel).

    START → read → extract → check ─┬─ ok ─────────────────→ write → done → END
                       ▲            ├─ abgelehnt, Runde < MAX_ROUNDS ─┘ (zurück zu extract)
                       │            └─ abgelehnt, Runde = MAX_ROUNDS → freigabe (interrupt)
                       └──────────── edit ─────────────────────┘   approve → write, reject → END

- read (Code): Rohtext pro Seite, Seitenbilder der visuellen Seiten. Das Original wird nur hier geöffnet.
- extract (Agent 1, Vision-Modell): Folientext, Zusammenfassung, Cheatsheet, Info-JSON.
- check (Agent 2, anderes Modell eines anderen Anbieters): prüft gegen den Rohtext.
- freigabe (HITL): interrupt() mit Entwurf und Beanstandung, Entscheid approve | edit | reject.
- write, done (Code): Dateien schreiben, Termine ergänzen, `study done`.
"""
import base64
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from study_agent.config import load_settings
from study_agent.llm import CHECK_MODEL, VISION_MODEL, chat_model
from study_agent.pipeline.modul import merge_modul

MAX_ROUNDS = 2
BLOCK = 8          # Seiten pro Abschreib-Aufruf
SCALE = 2.08       # 150 dpi
MAX_EDGE = 1600
MAX_INFO_IMAGES = 20
_SEITE = re.compile(r"^## Seite (\d+)\b.*$", re.M)

REGELN = """Regeln:
- Nur Inhalte aus dem Material. Nichts erfinden. Unsicheres mit „(unsicher: Grund)“ markieren.
- Keine Lösungen zu bewerteten Aufgaben, Projekten oder Prüfungen erstellen.
- Schweizer Rechtschreibung (ss statt ß). Englische Fachbegriffe bei englischem Material beibehalten."""

ABSCHREIBEN = """Du schreibst Vorlesungsfolien wörtlich ab. Du bekommst pro Seite den extrahierten Rohtext und bei \
manchen Seiten ein Seitenbild. Liefere für JEDE Seite genau eine Folie mit derselben Nummer.
- text: Folientext wörtlich, nichts weglassen, nicht umformulieren. Zerstückelte Zeilen anhand des Seitenbilds \
zusammensetzen. Formeln in LaTeX, Tabellen als Markdown. Vorlagenreste (Logo, Seitenzahl) weglassen.
- abbildung: nur bei Seiten mit Seitenbild und sichtbarer Abbildung: was sie zeigt, mit allen Zahlen und \
Beschriftungen, auf Deutsch. Sonst leer.
""" + REGELN

ARTEFAKTE = """Du bekommst den Folientext eines Foliensatzes (Route voll) oder den Rohtext eines Semesterprogramms \
bzw. einer Projektbeschreibung (Route info). Erstelle:
- zusammenfassung (nur Route voll, sonst leer): Markdown mit „## Überblick“ und pro wichtigem Konzept ein \
Abschnitt (was, wie, Abgrenzung, Folienverweise „(Folie N)“).
- cheatsheet (nur Route voll, sonst leer): höchstens eine A4-Seite Markdown, Formeln, Kurzdefinitionen, \
Merksätze, jeweils mit (Folie N).
- begriffe (nur Route voll): im Material definierte Fachbegriffe, Definition in 1 bis 2 Sätzen.
- termine: Bei Semesterprogrammen ALLE Termine (Lektionen, Abgaben, Präsentationen, Prüfungen). Bei normalen \
Folien nur Abgaben, Prüfungen, Präsentationen, Meilensteine, Präsenzpflicht, Ausfälle. Datum JJJJ-MM-TT; ein \
Datum ohne Jahr dem laufenden Semester zuordnen (heute ist {heute}; Herbstsemester September bis Januar). \
zeit nur, wenn sie ausdrücklich dasteht. Nie Termine erfinden.
- modul: nur ausdrücklich genannte Angaben, sonst null.
- projekt, pruefung: Anforderungen, Bewertung, Umfang, Form, Stoffabgrenzung.
- quelle immer als „<Dateiname>, Folie N“ bzw. „Seite N“.
""" + REGELN

PRUEFEN = """Du bist der Prüfer im Vier-Augen-Prinzip. Ein anderes Modell hat aus einer Unterlage einen Folientext \
und ein Info-JSON erstellt. Prüfe den Entwurf gegen den Rohtext (die zweite, unabhängige Quelle). Kriterien:
1. fehlt: eine Seite des Rohtexts hat keine Folie im Entwurf, oder wesentlicher Inhalt einer Folie fehlt.
2. zahl: eine Zahl, ein Datum oder ein Name im Entwurf weicht vom Rohtext ab.
3. termin: ein Termin im JSON steht so nicht im Rohtext (erfunden, falsches Datum, falsche Art).
4. sonstiges: erfundene Inhalte, die weder im Rohtext noch plausibel aus einem Seitenbild stammen.
Bei Route „info“ (Semesterprogramm, Projektbeschreibung) gibt es absichtlich KEINEN Folientext, nur das
Info-JSON: prüfe dann nur Termine, Zahlen und Angaben im JSON, fehlende Folien sind kein Fehler.
Bildbeschreibungen (Abbildung) und Umformatierungen (Markdown, LaTeX) sind KEIN Fehler. Kleine \
Abweichungen bei Zeilenumbrüchen ignorieren. ok=true nur, wenn es keine Beanstandung der Arten 1 bis 4 gibt. \
Sei streng bei Terminen und Zahlen, sonst grosszügig."""


# --- strukturierte Ausgaben ----------------------------------------------------------------------

class Folie(BaseModel):
    nummer: int
    titel: str
    text: str
    abbildung: str = Field(default="", description="Bildbeschreibung oder leer")


class Folien(BaseModel):
    folien: list[Folie]


class Begriff(BaseModel):
    begriff: str
    definition: str
    quelle: str


class Termin(BaseModel):
    datum: str = Field(description="JJJJ-MM-TT")
    zeit: str | None = Field(default=None, description="HH:MM oder null")
    titel: str
    art: Literal["abgabe", "pruefung", "praesentation", "meilenstein", "praesenz", "ausfall", "lektion", "termin"]
    quelle: str


class Modul(BaseModel):
    leistungsnachweis: Literal["pruefung", "projekt", "beides"] | None = None
    gewichtung: str | None = None
    dauer: str | None = None
    hilfsmittel: str | None = None
    daten: list[str] = []
    quellen: list[str] = []


class Info(BaseModel):
    info: str
    quelle: str


class Artefakte(BaseModel):
    zusammenfassung: str
    cheatsheet: str
    begriffe: list[Begriff]
    termine: list[Termin]
    modul: Modul
    projekt: list[Info]
    pruefung: list[Info]


class Beanstandung(BaseModel):
    folie: int | None = Field(description="Foliennummer oder null, wenn sie das JSON betrifft")
    art: Literal["fehlt", "zahl", "termin", "sonstiges"]
    beschreibung: str


class Pruefung(BaseModel):
    ok: bool
    beanstandungen: list[Beanstandung]


class Entscheid(BaseModel):
    """Antwort auf die Freigabe (Command(resume=...))."""
    decision: Literal["approve", "edit", "reject"]
    feedback: str = ""


# --- State ---------------------------------------------------------------------------------------

class VState(TypedDict, total=False):
    rel: str
    force: bool                  # auch bereits verarbeitete Dateien
    route: str
    sabotage: bool               # Demo: absichtlich fehlerhafte Extraktion
    texts: dict[str, str]        # Seite -> Rohtext
    images: dict[str, str]       # Seite -> PNG-Pfad
    folien: dict[str, dict]      # Seite -> Folie
    artefakte: dict
    feedback: str
    pruefung: dict
    runde: int
    entscheid: str
    geschrieben: list[str]


def _pending(rel: str, force: bool = True):
    from study_agent.cli import _current_ids, _overrides, _site_url
    from study_agent.pipeline.eigene import eigene_files
    from study_agent.pipeline.moodle_db import all_files
    from study_agent.pipeline.pending import pending_files

    s = load_settings()
    items = pending_files(s, all_files(s.moodle_db), _overrides(s), _site_url(s), None,
                          eigene=eigene_files(s.data_dir), include_done=force)
    pf = next((p for p in items if p.rel == rel), None)
    if pf is None:
        raise ValueError(f"{rel}: nicht offen (siehe `study pending --all`)")
    return pf


def raw_pages(raw_md: str) -> dict[int, str]:
    heads = list(_SEITE.finditer(raw_md))
    pages = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw_md)
        body = "\n".join(l for l in raw_md[m.end():end].splitlines() if not l.startswith("<!-- seite:"))
        pages[int(m.group(1))] = body.strip()
    return pages


def thread_id(rel: str) -> str:
    return "verarbeiten-" + hashlib.sha1(rel.encode()).hexdigest()[:12]


def _content(intro: str, nums: list[int], texts: dict[str, str], images: dict[str, str]) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": intro}]
    for n in nums:
        img = images.get(str(n))
        parts.append({"type": "text", "text": f"### Seite {n}{' (Seitenbild folgt)' if img else ''}\n"
                                              f"{texts.get(str(n), '') or '(kein Text)'}"})
        if img:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    return parts


def _folien_md(state: VState) -> str:
    out = []
    for n in sorted(state.get("folien", {}), key=int):
        f = state["folien"][n]
        block = f"## Folie {n} · {f['titel']}\n{f['text']}"
        if f.get("abbildung"):
            block += f"\n\n**Abbildung (beschrieben):** {f['abbildung']}"
        out.append(block)
    return "\n\n".join(out)


# --- Knoten --------------------------------------------------------------------------------------

def read(state: VState):
    """Code: Rohtext und Seitenbilder holen. Das Original-PDF wird nur hier geöffnet, einmal pro Datei."""
    pf = _pending(state["rel"], force=state.get("force", False))
    texts = raw_pages(pf.raw_md.read_text())
    visual = pf.visual if pf.route == "voll" else pf.visual[:MAX_INFO_IMAGES]
    images: dict[str, str] = {}
    if pf.source.suffix.lower() == ".pdf" and visual:
        import pypdfium2 as pdfium

        out_dir = load_settings().state_dir / "seiten" / thread_id(pf.rel)
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = pdfium.PdfDocument(pf.source)
        try:
            for n in visual:
                if 1 <= n <= len(doc):
                    img = doc[n - 1].render(scale=SCALE).to_pil()
                    img.thumbnail((MAX_EDGE, MAX_EDGE))
                    path = out_dir / f"{n}.png"
                    img.save(path, "PNG")
                    images[str(n)] = str(path)
        finally:
            doc.close()
    # neuer Lauf im selben Thread: Werte des vorigen Laufs zurücksetzen
    return {"route": pf.route, "texts": {str(k): v for k, v in texts.items()}, "images": images, "runde": 0,
            "feedback": "", "folien": {}, "pruefung": {}, "entscheid": "", "geschrieben": []}


def extract(state: VState):
    """Agent 1 (Vision-Modell). In Runde 2 nur die beanstandeten Folien neu, plus Artefakte mit Feedback."""
    pf = _pending(state["rel"])
    llm = chat_model(VISION_MODEL)
    texts, images = state["texts"], state["images"]
    folien = dict(state.get("folien") or {})
    feedback = state.get("feedback", "")
    hinweis = f"\n\nDer Prüfer hat Folgendes beanstandet, bitte korrigieren:\n{feedback}" if feedback else ""

    if state["route"] == "voll":
        alle = sorted(int(k) for k in texts) or list(range(1, (pf.pages or 0) + 1))
        beanstandet = {b["folie"] for b in (state.get("pruefung") or {}).get("beanstandungen", []) if b.get("folie")}
        todo = [n for n in alle if str(n) not in folien or n in beanstandet]
        abschreiber = llm.with_structured_output(Folien, method="json_schema")

        def run(nums: list[int]) -> list[Folie]:
            intro = f"Foliensatz „{pf.name}“, Seiten {nums[0]} bis {nums[-1]}.{hinweis}"
            res: Folien = abschreiber.invoke([{"role": "system", "content": ABSCHREIBEN},
                                              {"role": "user", "content": _content(intro, nums, texts, images)}])
            return [f for f in res.folien if f.nummer in nums]

        with ThreadPoolExecutor(max_workers=3) as pool:
            for got in pool.map(run, [todo[i:i + BLOCK] for i in range(0, len(todo), BLOCK)]):
                folien.update({str(f.nummer): f.model_dump() for f in got})
        material = _folien_md({"folien": folien})
    else:
        material = "\n\n".join(f"## Seite {k}\n{v}" for k, v in sorted(texts.items(), key=lambda kv: int(kv[0])))

    art: Artefakte = llm.with_structured_output(Artefakte, method="json_schema").invoke([
        {"role": "system", "content": ARTEFAKTE.format(heute=f"{date.today():%Y-%m-%d}")},
        {"role": "user", "content": f"Kurs: {pf.course}\nDatei: {pf.name}\nRoute: {state['route']}{hinweis}\n\n{material}"},
    ])
    artefakte = art.model_dump()

    if state.get("sabotage"):
        # Demo für die Freigabe: eine Folie fehlt und ein erfundener Termin ist drin
        if folien:
            folien.pop(sorted(folien, key=int)[len(folien) // 2], None)
        artefakte["termine"].append({"datum": "2026-12-24", "zeit": "18:00", "titel": "Pflichtabgabe Weihnachtsbericht",
                                     "art": "abgabe", "quelle": f"{pf.name}, Folie 1"})
    return {"folien": folien, "artefakte": artefakte, "runde": state.get("runde", 0) + 1}


def check(state: VState):
    """Agent 2 (anderes Modell): prüft Entwurf gegen den Rohtext. Fehlende Folien zusätzlich im Code."""
    rohtext = "\n\n".join(f"## Seite {k}\n{v}" for k, v in sorted(state["texts"].items(), key=lambda kv: int(kv[0])))
    a = state["artefakte"]
    entwurf = json.dumps({k: a[k] for k in ("termine", "modul", "projekt", "pruefung")}, ensure_ascii=False, indent=1)
    if state["route"] == "voll":
        entwurf = _folien_md(state) + "\n\n# Info-JSON\n" + entwurf
    pruefer = chat_model(CHECK_MODEL).with_structured_output(Pruefung, method="json_schema")
    p: Pruefung = pruefer.invoke([
        {"role": "system", "content": PRUEFEN},
        {"role": "user", "content": f"Route: {state['route']}\n\n# Rohtext\n{rohtext}\n\n# Entwurf\n{entwurf}"},
    ])
    # harte Regel im Code: jede Seite braucht eine Folie (wie `study check-folien`)
    if state["route"] == "voll":
        fehlend = [int(k) for k in state["texts"] if k not in state["folien"]]
        for n in sorted(fehlend):
            if not any(b.folie == n and b.art == "fehlt" for b in p.beanstandungen):
                p.beanstandungen.append(Beanstandung(folie=n, art="fehlt", beschreibung=f"Folie {n} fehlt im Entwurf"))
        p.ok = p.ok and not fehlend
    feedback = "\n".join(f"- [{b.art}] Folie {b.folie}: {b.beschreibung}" if b.folie else f"- [{b.art}] {b.beschreibung}"
                         for b in p.beanstandungen)
    return {"pruefung": p.model_dump(), "feedback": feedback}


def after_check(state: VState):
    if state["pruefung"]["ok"]:
        return "write"
    return "extract" if state["runde"] < MAX_ROUNDS else "freigabe"


def freigabe(state: VState) -> Command[Literal["write", "extract", "__end__"]]:
    """HITL (SW8): nur wenn die Prüfung nach MAX_ROUNDS noch ablehnt."""
    a = state["artefakte"]
    antwort = interrupt({
        "art": "freigabe",
        "rel": state["rel"],
        "runden": state["runde"],
        "beanstandungen": state["pruefung"]["beanstandungen"],
        "entwurf": {"folien": len(state.get("folien") or {}), "seiten": len(state["texts"]),
                    "termine": a["termine"], "zusammenfassung": (a.get("zusammenfassung") or "")[:1500]},
        "optionen": ["approve", "edit", "reject"],
    })
    e = Entscheid.model_validate(antwort if isinstance(antwort, dict) else {"decision": antwort})
    if e.decision == "approve":
        return Command(goto="write", update={"entscheid": "approve"})
    if e.decision == "edit":
        # zusätzliche Runde mit dem Feedback der Person, Sabotage aus
        return Command(goto="extract", update={"entscheid": "edit", "feedback": e.feedback, "sabotage": False,
                                               "runde": MAX_ROUNDS - 1})
    return Command(goto=END, update={"entscheid": "reject"})


def _merge_termine(course: str, course_id: int, termine: list[dict]) -> int:
    """Neue Termine an termine/<Kurs>.yaml anhängen (Duplikate nach Datum und Titel übersprungen)."""
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)  # wie die von Hand gepflegten Dateien
    path = load_settings().termine_dir / f"{course}.yaml"
    data = yaml.load(path.read_text()) if path.exists() else {"kurs": course, "kurs_id": course_id, "termine": []}
    data.setdefault("termine", [])
    from difflib import SequenceMatcher

    def gleich(a: str, b: str) -> bool:
        a, b = a.casefold(), b.casefold()
        return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.6

    vorhanden: list[tuple[str, str, str]] = [(str(t.get("datum")), str(t.get("titel")), str(t.get("art"))) for t in data["termine"]]
    neu = 0
    for t in termine:
        try:
            tag = date.fromisoformat(t["datum"])
        except (ValueError, TypeError):
            continue
        # derselbe Termin: gleiches Datum und ähnlicher Titel, oder gleiches Datum und gleiche Art bei Abgaben/Prüfungen
        if any(d == str(tag) and (gleich(ti, t["titel"]) or (a == t["art"] and a in ("abgabe", "pruefung")))
               for d, ti, a in vorhanden):
            continue
        vorhanden.append((str(tag), t["titel"], t["art"]))
        eintrag = {"datum": tag, "titel": Q(t["titel"]), "art": t["art"], "quelle": Q(t["quelle"])}
        if t.get("zeit"):
            eintrag["zeit"] = Q(t["zeit"])  # gequotet, sonst liest YAML 1.1 „08:30“ als Zahl
        data["termine"].append(eintrag)
        neu += 1
    if neu:
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        yaml.dump(data, buf)
        path.write_text(buf.getvalue())
    return neu


def write(state: VState):
    """Code: Dateien schreiben, Termine ergänzen."""
    pf = _pending(state["rel"])
    a = state["artefakte"]
    out: list[str] = []
    stem = Path(pf.name).stem
    if state["route"] == "voll":
        header = (f"<!-- source: {pf.source.name} · moodle: {pf.moodle_link} · extrahiert: {date.today():%Y-%m-%d} · "
                  f"Seitenbilder: {pf.visual} · modell: {VISION_MODEL} · geprueft: {CHECK_MODEL} -->\n# {pf.name}\n")
        pf.folien_md.parent.mkdir(parents=True, exist_ok=True)
        pf.folien_md.write_text(header + "\n" + _folien_md(state) + "\n")
        out.append(str(pf.folien_md))
        pf.lernen_dir.mkdir(parents=True, exist_ok=True)
        for teil, titel in (("zusammenfassung", f"# {stem} – Zusammenfassung"), ("cheatsheet", f"# Cheatsheet {stem}")):
            if a.get(teil):
                p = pf.lernen_dir / f"{stem}.{teil}.md"
                p.write_text(f"{titel}\n\nQuelle: `{pf.rel}`\n\n{a[teil]}\n")
                out.append(str(p))
    if pf.course_lernen_dir:
        merge_modul(pf.course_lernen_dir, pf.name, a.get("modul") or {}, a.get("pruefung"), a.get("projekt"))
    neu = _merge_termine(pf.course, pf.course_id, a.get("termine") or [])
    out.append(f"termine: {neu} neu")
    return {"geschrieben": out}


def done(state: VState):
    """Code: Datei als verarbeitet markieren (`study done`). Bei Route voll nur mit vollständiger .folien.md."""
    from study_agent.cli import _overrides
    from study_agent.pipeline.pending import finish

    s = load_settings()
    try:
        finish(s, state["rel"], _overrides(s))
    except ValueError as exc:
        # Nach einer Freigabe trotz fehlender Folien bleibt die Datei offen
        return {"geschrieben": [*state.get("geschrieben", []), f"nicht abgeschlossen: {exc}"]}
    return {}


def build_verarbeiten_graph(checkpointer=None):
    g = StateGraph(VState)
    g.add_node("read", read)
    g.add_node("extract", extract)
    g.add_node("check", check)
    g.add_node("freigabe", freigabe, destinations=("write", "extract", END))
    g.add_node("write", write)
    g.add_node("done", done)
    g.add_edge(START, "read")
    g.add_edge("read", "extract")
    g.add_edge("extract", "check")
    g.add_conditional_edges("check", after_check, ["write", "extract", "freigabe"])
    g.add_edge("write", "done")
    g.add_edge("done", END)
    return g.compile(checkpointer=checkpointer)


def checkpointer_path() -> Path:
    s = load_settings()
    s.state_dir.mkdir(parents=True, exist_ok=True)
    return s.state_dir / "verarbeiten.sqlite"


def open_freigaben(graph) -> list[dict]:
    """Alle Threads, die in der Freigabe warten (für CLI und Dashboard)."""
    out = []
    # Thread-IDs zuerst vollständig einsammeln: list() hält das SQLite-Lock, solange der Generator läuft
    tids = sorted({cp.config["configurable"]["thread_id"] for cp in graph.checkpointer.list(None)})
    for tid in tids:
        st = graph.get_state({"configurable": {"thread_id": tid}})
        for task in st.tasks:
            for intr in task.interrupts:
                out.append({"thread_id": tid, **intr.value})
    return out
