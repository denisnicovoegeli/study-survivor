"""Dateien klassifizieren: Name/Aktivität zuerst, dann Seitenformat; Korrekturen aus klassen.yaml gelten vor."""
import re
import statistics
from pathlib import Path

import yaml

from study_agent.pipeline.pdf_pages import PageInfo

AUTO_CLASSES = ("folien", "semesterprogramm", "projekt", "loesung", "uebung", "literatur", "unklar")
CLASSES = frozenset({*AUTO_CLASSES, "ueberspringen"})
# Wie /verarbeiten eine Klasse behandelt; Klassen ohne Eintrag werden nicht verarbeitet.
ROUTES = {"folien": "voll", "semesterprogramm": "info", "projekt": "info", "unklar": "fragen"}
LITERATURE_MIN_PAGES = 150
SLIDE_MIN_LANDSCAPE_SHARE = 0.75
SLIDE_MAX_MEDIAN_CHARS = 1500
NAME_RULES = (  # Reihenfolge zählt: „Lösung Übung 1“ ist eine Lösung
    ("semesterprogramm", re.compile(r"programm|semesterplan|zeitplan|schedule|modulbeschreibung|lernziel")),
    ("projekt", re.compile(r"wegleitung|leistungsnachweis|projektthemen|projektbeschreibung|aufgabenstellung"
                           r"|bewertungsraster|rubric")),
    ("loesung", re.compile(r"lösung|loesung|solution|musterl")),
    ("uebung", re.compile(r"übung|uebung|exercise|aufgabe|assignment|tutorial|(?<![a-z])u\d{1,2}(?!\d)")),
    ("literatur", re.compile(r"paper|artikel|article|literatur|reading|chapter|kapitel|(?<![a-z])book|(?<![a-z])buch")),
    ("folien", re.compile(r"folien|slides|vorlesung|lecture|unterricht|session|(?<![a-z])s?w\d{1,2}(?!\d)")),
)


def classify(name: str, module_name: str, suffix: str, pages: list[PageInfo] | None = None) -> str:
    text = f"{name} {module_name}".casefold()
    for klasse, rule in NAME_RULES:
        if rule.search(text):
            return klasse
    if suffix == ".pptx":
        return "folien"
    if suffix == ".pdf" and pages:
        if len(pages) > LITERATURE_MIN_PAGES:
            return "literatur"
        landscape = sum(p.landscape for p in pages) / len(pages)
        median_chars = statistics.median(len(p.text) for p in pages)
        if landscape >= SLIDE_MIN_LANDSCAPE_SHARE and median_chars < SLIDE_MAX_MEDIAN_CHARS:
            return "folien"
    return "unklar"


def load_overrides(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.exists():
        return {}, []
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return {}, [f"{path.name}: {exc}"[:200]]
    if not isinstance(raw, dict):
        return {}, [f"{path.name}: erwartet Zuordnung „Pfad: Klasse“"]
    good, errors = {}, []
    for rel, klasse in raw.items():
        if klasse in CLASSES:
            good[str(rel)] = klasse
        else:
            errors.append(f"{path.name}: {rel}: Klasse {klasse!r} unbekannt")
    return good, errors


def set_override(path: Path, rel: str, klasse: str) -> None:
    if klasse not in CLASSES:
        raise ValueError(f"Klasse {klasse!r} unbekannt, erlaubt: {', '.join(sorted(CLASSES))}")
    current, errors = load_overrides(path)
    if errors:
        raise ValueError(f"{path.name} zuerst korrigieren: {errors[0]}")
    current[rel] = klasse
    path.write_text(yaml.safe_dump(dict(sorted(current.items())), allow_unicode=True, sort_keys=False))
