"""Module: Moodle-Kurse (Ordner von moodle-dl) und eigene Module ohne Moodle (_eigene/<Name>/).

Ein eigenes Modul ist ein Ordner unter _eigene/, dessen Name kein Moodle-Kurs ist.
Hochgeladene Dateien darin verarbeitet der Agent wie Moodle-Material (convert,
pending und verarbeiten kennen _eigene/ bereits).
"""
from pathlib import Path

from study_agent.pipeline.eigene import EIGENE_DIR, _sanitize_course, eigene_dir

QUELLE_MOODLE = "moodle"
QUELLE_EIGENE = "eigene"


def moodle_kurse(data_dir: Path) -> list[str]:
    """Kursordner von moodle-dl (alles ausser _eigene, versteckten und Hilfsordnern)."""
    if not data_dir.is_dir():
        return []
    return sorted(p.name for p in data_dir.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")))


def eigene_module(data_dir: Path) -> list[str]:
    root = eigene_dir(data_dir)
    if not root.is_dir():
        return []
    moodle = {n.casefold() for n in moodle_kurse(data_dir)}
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and p.name.casefold() not in moodle)


def quelle(data_dir: Path, name: str) -> str:
    return QUELLE_EIGENE if name in eigene_module(data_dir) else QUELLE_MOODLE


def modul_anlegen(data_dir: Path, name: str) -> str:
    """Legt _eigene/<Name>/ an. ValueError bei ungültigem oder schon vergebenem Namen."""
    name = _sanitize_course(name or "")
    if len(name) > 80:
        raise ValueError("Modulname: höchstens 80 Zeichen")
    vorhanden = {n.casefold() for n in moodle_kurse(data_dir) + eigene_module(data_dir)}
    if name.casefold() in vorhanden:
        raise ValueError(f"Ein Modul «{name}» gibt es schon")
    (eigene_dir(data_dir) / name).mkdir(parents=True)
    return name


def dateien(data_dir: Path, name: str) -> list[Path]:
    root = eigene_dir(data_dir) / name
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")) if root.is_dir() else []


def modul_entfernen(data_dir: Path, name: str) -> None:
    """Entfernt ein leeres eigenes Modul. Mit Dateien darin wird nichts gelöscht (ValueError)."""
    if name not in eigene_module(data_dir):
        raise ValueError(f"«{name}» ist kein eigenes Modul")
    if dateien(data_dir, name):
        raise ValueError(f"«{name}» enthält noch Dateien. Entferne sie zuerst im Ordner {EIGENE_DIR}/{name}.")
    root = eigene_dir(data_dir) / name
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()  # nur versteckte Dateien (.DS_Store) und leere Ordner
    root.rmdir()
