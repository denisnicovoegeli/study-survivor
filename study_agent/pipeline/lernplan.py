"""Lernplan bis zur Prüfung: Themen eines Moduls rückwärts vom Prüfungsdatum auf Wochen verteilen.

Themen sind die Abschnitte (Wochen) eines Moduls. Offene Themen werden gleichmässig
auf die Wochen bis vor der Prüfung verteilt, die letzte Woche ist für Wiederholung
und Karteikarten reserviert. Der Plan wird bei jedem Aufruf neu gerechnet: erledigte
Themen fallen weg, neue Abschnitte aus Moodle kommen automatisch dazu.
"""
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATEI = "lernplan.json"
_TAG = re.compile(r"[<＜][^>＞]*[>＞]")
_OHNE_STOFF = frozenset({"allgemein", "allgemeines", "general", "(ohne abschnitt)"})


@dataclass(frozen=True)
class Thema:
    id: str  # Abschnittsname wie im Lernordner
    name: str  # lesbar
    aufbereitet: bool  # Zusammenfassung vorhanden


def thema_name(abschnitt: str) -> str:
    """Moodle-Abschnittsnamen lesbar machen (HTML-Reste, Vollbreiten-Doppelpunkt)."""
    text = _TAG.sub("", abschnitt).replace("：", ":").replace("⧸", "/")
    return " ".join(text.split()) or abschnitt


_NUMMER = re.compile(r"^(?:woche\s*)?(\d+(?:\.\d+)?)\b", re.I)
_UEBERSCHRIFT = re.compile(r"^## (.+)$", re.M)


def reihenfolge(index_md: str) -> list[str]:
    """Abschnittsnamen in Moodle-Reihenfolge aus knowledge/<Kurs>/INDEX.md."""
    return [thema_name(m) for m in _UEBERSCHRIFT.findall(index_md)]


def _nummer(name: str) -> float | None:
    m = _NUMMER.match(name)
    return float(m.group(1)) if m else None


def themen_aus_wochen(wochen: list[dict], ordnung: list[str] | None = None) -> list[Thema]:
    """Themen aus fortschritt.wochen der Modulansicht, ohne allgemeine Abschnitte.

    Gleich lautende Abschnitte (Moodle liefert manche mit HTML-Resten doppelt) werden zusammengelegt.
    Reihenfolge wie in Moodle (ordnung); nummerierte Abschnitte werden untereinander nach Nummer sortiert.
    """
    gesehen: dict[str, Thema] = {}
    for w in wochen:
        sec = str(w.get("section") or "")
        name = thema_name(sec)
        if not sec or name.casefold() in _OHNE_STOFF or not w.get("total"):
            continue
        alt = gesehen.get(name)
        gesehen[name] = Thema(name, name, bool(w.get("verarbeitet")) or (alt.aufbereitet if alt else False))
    pos = {n: i for i, n in enumerate(ordnung or [])}
    themen = sorted(gesehen.values(), key=lambda t: (pos.get(t.name, len(pos)), _nummer(t.name) or 0, t.name))
    nummeriert = sorted((t for t in themen if _nummer(t.name) is not None), key=lambda t: _nummer(t.name))
    it = iter(nummeriert)
    return [next(it) if _nummer(t.name) is not None else t for t in themen]


def plan_start(heute: date) -> date:
    """Montag der laufenden Woche, am Wochenende schon der nächsten."""
    return montag(heute) + (timedelta(days=7) if heute.weekday() >= 5 else timedelta())


def montag(d: date) -> date:
    return d - timedelta(days=d.weekday())


def modul_plan(themen: list[Thema], pruefung: date, heute: date, erledigt: set[str]) -> list[dict]:
    """Wochen von heute bis zur Prüfungswoche, je mit Themen. Leer, wenn die Prüfung vorbei ist."""
    if pruefung < heute:
        return []
    wochen = []
    w = plan_start(heute)
    while w <= pruefung:
        wochen.append(w)
        w += timedelta(days=7)
    wochen = wochen or [montag(heute)]  # Prüfung noch an diesem Wochenende
    offen = [t for t in themen if t.id not in erledigt]
    # Wiederholung: die Woche mit den vier Tagen vor der Prüfung (Prüfung am Montag → schon die Woche davor)
    ab = montag(pruefung - timedelta(days=4))
    lernwochen = [w for w in wochen if w < ab] or wochen
    k, n = len(lernwochen), len(offen)
    out = []
    for i, start in enumerate(wochen):
        themen_w = offen[i * n // k:(i + 1) * n // k] if i < k else []
        out.append({
            "start": start.isoformat(),
            "themen": [{"id": t.id, "name": t.name, "aufbereitet": t.aufbereitet} for t in themen_w],
            "wiederholung": start >= ab or start == wochen[-1],
            "pruefung": pruefung.isoformat() if start <= pruefung < start + timedelta(days=7) else None,
        })
    return out


def karten_stand(karten: list[dict]) -> dict:
    """Leitner-Stand: wie viele Karten in Fach 1–3 (Fach 3 = sitzt)."""
    faecher = [int(c.get("box") or 1) for c in karten]
    return {"total": len(faecher), "fach1": faecher.count(1), "fach2": faecher.count(2), "fach3": faecher.count(3)}


def zusammenfuehren(plaene: dict[str, list[dict]]) -> list[dict]:
    """Pläne mehrerer Module zu einer Wochenliste: {start, module: [{modul, themen, wiederholung, pruefung}]}."""
    wochen: dict[str, list[dict]] = {}
    for modul, plan in plaene.items():
        for w in plan:
            if w["themen"] or w["wiederholung"] or w["pruefung"]:
                wochen.setdefault(w["start"], []).append({"modul": modul, **{k: w[k] for k in
                                                          ("themen", "wiederholung", "pruefung")}})
    return [{"start": s, "module": sorted(m, key=lambda x: x["modul"])} for s, m in sorted(wochen.items())]


def laden(state_dir: Path) -> dict[str, list[str]]:
    p = state_dir / DATEI
    try:
        d = json.loads(p.read_text()) if p.exists() else {}
        return {k: [str(x) for x in v] for k, v in d.items() if isinstance(v, list)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def erledigt_setzen(state_dir: Path, modul: str, thema: str, erledigt: bool) -> list[str]:
    d = laden(state_dir)
    liste = [t for t in d.get(modul, []) if t != thema] + ([thema] if erledigt else [])
    if liste:
        d[modul] = liste
    else:
        d.pop(modul, None)
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / DATEI
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    tmp.replace(p)
    return liste
