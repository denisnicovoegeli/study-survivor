"""Lokale Tools des Chat-Graphen (SW5/SW6): Termine und Hybrid-Suche im Kursmaterial."""
from datetime import datetime, timezone

from langchain_core.tools import tool

from study_agent.config import load_moodle_config, load_settings
from study_agent.pipeline.briefing import TZ
from study_agent.pipeline.moodle_api import MoodleClient, MoodleError
from study_agent.pipeline.termine import load_termine, merge_deadlines, upcoming_termine, zusammenfuehren


def _fmt(d) -> str:
    when = d.due.astimezone(TZ).strftime("%a %d.%m.%Y" if d.all_day else "%a %d.%m.%Y %H:%M")
    quelle = d.source or "Moodle-Kalender"
    return f"- {when} · {d.kind} · {d.course}: {d.name} [Quelle: {quelle}]"


@tool
def termine(tage: int = 30, kurs: str | None = None) -> str:
    """Kommende Termine, Abgaben, Prüfungen und Präsentationen der aktuellen Kurse.

    Kombiniert den Moodle-Kalender mit den geprüften Terminen aus dem Kursmaterial
    (termine/*.yaml, die meisten Termine stehen nur dort). Für jede Frage nach
    Daten, Fristen, Deadlines, "wann ist ..." oder "was steht an" dieses Tool nutzen,
    nie aus dem Gedächtnis antworten.

    Args:
        tage: Zeitraum ab heute in Tagen (Standard 30, für ein ganzes Semester 120).
        kurs: optionaler Teil des Kursnamens, z. B. "Deep Learning" oder "GenAI".
    """
    settings = load_settings()
    now = datetime.now(timezone.utc)
    local, errors = load_termine(settings.termine_dir)
    local = zusammenfuehren(upcoming_termine(local, now, tage))
    hinweis = ""
    try:
        client = MoodleClient(load_moodle_config(settings.moodle_config_path))
        moodle = client.upcoming_deadlines(days=tage)
    except (MoodleError, OSError, ValueError) as exc:
        moodle = []
        hinweis = f"\n(Hinweis: Moodle-Kalender nicht erreichbar: {type(exc).__name__})"
    events = merge_deadlines(moodle, local)
    if kurs:
        k = kurs.casefold().replace("genai", "generative ki")
        events = [e for e in events if k in e.course.casefold()]
    if errors:
        hinweis += f"\n(Hinweis: {len(errors)} Termindatei(en) mit Fehlern)"
    if not events:
        return f"Keine Termine in den nächsten {tage} Tagen." + hinweis
    heute = datetime.now(TZ).strftime("%a %d.%m.%Y")
    return f"Heute: {heute}\n" + "\n".join(_fmt(e) for e in events) + hinweis


@tool
def kursmaterial_suchen(frage: str, kurs: str | None = None, anzahl: int = 5) -> str:
    """Durchsucht Folien und Unterlagen aller aktuellen Kurse (Hybrid: Volltext BM25 plus semantische Suche).

    Für jede inhaltliche Frage zuerst dieses Tool nutzen. Liefert pro Fundstelle
    die Quelle (Kurs / Datei / Folie) und den Text. Mehrere Suchen mit anderen
    Stichwörtern sind erlaubt, wenn die erste nichts Passendes bringt.

    Args:
        frage: Frage oder Stichwörter, z. B. "Reciprocal Rank Fusion" oder "Checkpointer thread_id".
        kurs: optionaler Teil des Kursnamens, um die Suche einzuschränken.
        anzahl: Anzahl Fundstellen (1 bis 10).
    """
    from study_agent.agent.rag import hybrid_search

    hits = hybrid_search(frage, kurs=kurs, k=max(1, min(anzahl, 10)))
    if not hits:
        return "Keine Fundstellen im Kursmaterial."
    out = []
    for h in hits:
        text = h.text.strip().replace("\n\n", "\n")
        out.append(f"### Quelle: {h.quelle()}  (via {'+'.join(h.via)})\n{text[:1500]}")
    return "\n\n".join(out)


LOCAL_TOOLS = [termine, kursmaterial_suchen]
