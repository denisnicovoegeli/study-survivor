"""Was /verarbeiten noch tun muss: offene Dateien, Vollständigkeit der .folien.md, Abschluss pro Datei."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from study_agent.pipeline.classify import ROUTES
from study_agent.config import Settings
from study_agent.einstellungen import laden as laden_einstellungen, ueberspringen_grund
from study_agent.pipeline.convert import folien_path, knowledge_path, load_manifest
from study_agent.pipeline.eigene import EigeneFile
from study_agent.pipeline.moodle_db import FileRecord

DONE_FILE = "verarbeitet.json"
ROUTE_ORDER = {"fragen": 0, "info": 1, "voll": 2}  # erst nachfragen, dann Semesterprogramme, dann Folien
_FOLIE = re.compile(r"^## Folie (\d+)\b", re.M)


@dataclass(frozen=True)
class PendingFile:
    rel: str
    course: str
    course_id: int
    section: str
    name: str
    klasse: str
    route: str  # voll | info | fragen
    reason: str  # neu | veraltet
    pages: int | None
    visual: list[int]
    source: Path  # Original im moodle-dl-Ordner
    raw_md: Path  # knowledge/<rel>.md (Rohtext von convert)
    folien_md: Path  # knowledge/<rel>.folien.md (von Claude, nur Route „voll“)
    lernen_dir: Path  # lernen/<Kurs>/<Abschnitt>
    course_lernen_dir: Path  # lernen/<Kurs>
    moodle_link: str


def read_done(state_dir: Path) -> dict[str, list[int]]:
    path = state_dir / DONE_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def pending_files(settings: Settings, records: list[FileRecord], overrides: dict[str, str], site_url: str,
                  course_ids: set[int] | None = None,
                  eigene: list[EigeneFile] | None = None, include_done: bool = False) -> list[PendingFile]:
    manifest = load_manifest(settings.knowledge_dir)
    done = read_done(settings.state_dir)
    e = laden_einstellungen(settings.state_dir)
    filt = {**e["filter"], "archiv": e["semester"]["archiv"]}
    from study_agent.pipeline.ausschluss import laden as laden_ausschluss
    aus = laden_ausschluss(settings.state_dir)  # im Dashboard abgewählt: nicht zusammenfassen
    seen: set[str] = set()
    out = []
    for r in records:
        rel = r.rel(settings.data_dir)
        if rel is None or (course_ids is not None and r.course_id not in course_ids):
            continue
        key = rel.as_posix()
        entry = manifest.get(key)
        if entry is None or key in seen or key in aus:
            continue
        seen.add(key)
        klasse = overrides.get(key, entry["klasse"])
        route = ROUTES.get(klasse)
        if route is None or (not include_done and done.get(key) == entry["sig"]):
            continue
        if ueberspringen_grund(filt, r.course, rel.name, settings.data_dir / rel, route):
            continue
        out.append(PendingFile(
            rel=key, course=r.course, course_id=r.course_id, section=r.section, name=rel.name, klasse=klasse,
            route=route, reason="veraltet" if key in done else "neu", pages=entry.get("seiten"),
            visual=entry.get("visuell", []), source=settings.data_dir / rel,
            raw_md=knowledge_path(settings.knowledge_dir, rel), folien_md=folien_path(settings.knowledge_dir, rel),
            lernen_dir=settings.lernen_dir / rel.parent, course_lernen_dir=settings.lernen_dir / rel.parts[0],
            moodle_link=r.moodle_link(site_url),
        ))
    for e in eigene or []:
        rel = e.rel(settings.data_dir)
        if rel is None:
            continue
        key = rel.as_posix()
        entry = manifest.get(key)
        if entry is None or key in seen or key in aus:
            continue
        seen.add(key)
        klasse = overrides.get(key, entry["klasse"])
        route = ROUTES.get(klasse)
        if route is None or (not include_done and done.get(key) == entry["sig"]):
            continue
        if ueberspringen_grund(filt, e.course, rel.name, e.path, route):
            continue
        # Eigene Dateien haben keinen Moodle-Kurs und keinen Abschnitt; Lernartefakte
        # landen direkt unter lernen/<Kurs>/.
        lernen = settings.lernen_dir / e.course
        out.append(PendingFile(
            rel=key, course=e.course, course_id=-1, section="", name=rel.name, klasse=klasse,
            route=route, reason="veraltet" if key in done else "neu", pages=entry.get("seiten"),
            visual=entry.get("visuell", []), source=e.path,
            raw_md=knowledge_path(settings.knowledge_dir, rel), folien_md=folien_path(settings.knowledge_dir, rel),
            lernen_dir=lernen, course_lernen_dir=lernen,
            moodle_link="",
        ))
    return sorted(out, key=lambda p: (ROUTE_ORDER[p.route], p.course, p.rel))


def check_folien(folien_md: Path, pages: int) -> list[int]:
    """Foliennummern 1..pages, für die in der .folien.md kein Abschnitt „## Folie N“ existiert."""
    found = {int(n) for n in _FOLIE.findall(folien_md.read_text())} if folien_md.exists() else set()
    return [n for n in range(1, pages + 1) if n not in found]


def finish(settings: Settings, rel: str, overrides: dict[str, str]) -> None:
    """Markiert eine Datei als verarbeitet. Route „voll“ nur, wenn die .folien.md vollständig ist."""
    entry = load_manifest(settings.knowledge_dir).get(rel)
    if entry is None:
        raise ValueError(f"{rel}: nicht in knowledge/.manifest.json (zuerst `study convert`)")
    route = ROUTES.get(overrides.get(rel, entry["klasse"]))
    if route == "fragen":
        raise ValueError(f"{rel}: Klasse noch unklar, zuerst `study klasse` setzen")
    if route == "voll":
        if not entry.get("seiten"):
            raise ValueError(f"{rel}: Seitenzahl unbekannt, Vollständigkeit nicht prüfbar")
        missing = check_folien(folien_path(settings.knowledge_dir, Path(rel)), entry["seiten"])
        if missing:
            raise ValueError(f"{rel}: in der .folien.md fehlen Folien {missing}")
    done = read_done(settings.state_dir)
    done[rel] = entry["sig"]
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / DONE_FILE).write_text(json.dumps(done, ensure_ascii=False, indent=1))
