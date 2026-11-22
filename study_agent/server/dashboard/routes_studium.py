"""Routen für Modulübersicht, eigene Module und den Bereich «Studium» (modulübergreifende Dokumente).

Studium-Dokumente liegen in <Projekt>/studium/. Gelöschte Dokumente wandern nach
studium/.papierkorb/ und lassen sich von Hand zurückholen.
"""
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from study_agent import einstellungen
from study_agent.pipeline import lernplan
from study_agent.pipeline import module as module_lib
from study_agent.pipeline import modulfarben
from study_agent.pipeline import pruefungsplan

STUDIUM_DIR = "studium"
PAPIERKORB = ".papierkorb"
STUDIUM_ENDUNGEN = frozenset({".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".md", ".txt"})
MAX_GROESSE = 50 * 1024 * 1024
OHNE_MODUL = "Studium"  # Kursname für Prüfungen, die keinem Modul zugeordnet sind


def studium_dir(project_dir: Path) -> Path:
    return project_dir / STUDIUM_DIR


def studium_datei(project_dir: Path, name: str) -> Path:
    """Pfad einer Datei direkt in studium/. ValueError bei Pfadbestandteilen oder fehlender Datei."""
    if not name or name != Path(name).name or name.startswith("."):
        raise ValueError("Ungültiger Dateiname")
    pfad = studium_dir(project_dir) / name
    if not pfad.is_file():
        raise ValueError(f"{name}: nicht gefunden")
    return pfad


def studium_liste(project_dir: Path) -> List[Dict[str, Any]]:
    root = studium_dir(project_dir)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in STUDIUM_ENDUNGEN:
            continue
        st = p.stat()
        out.append({
            "name": p.name,
            "groesse": st.st_size,
            "geaendert": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "endung": p.suffix.lower().lstrip("."),
        })
    return out


def studium_speichern(project_dir: Path, dateiname: str, daten: bytes) -> str:
    name = Path(dateiname or "").name.strip()
    endung = Path(name).suffix.lower()
    if not name or name.startswith("."):
        raise ValueError("Dateiname fehlt")
    if endung not in STUDIUM_ENDUNGEN:
        raise ValueError(f"{name}: nur {', '.join(sorted(STUDIUM_ENDUNGEN))} erlaubt")
    if not daten:
        raise ValueError(f"{name}: Datei ist leer")
    if len(daten) > MAX_GROESSE:
        raise ValueError(f"{name}: grösser als 50 MB")
    root = studium_dir(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    ziel = root / name
    stamm = name[: -len(endung)]
    i = 2
    while ziel.exists():  # nie überschreiben
        ziel = root / f"{stamm}-{i}{endung}"
        i += 1
    ziel.write_bytes(daten)
    return ziel.name


def studium_entfernen(project_dir: Path, name: str) -> str:
    pfad = studium_datei(project_dir, name)
    korb = studium_dir(project_dir) / PAPIERKORB
    korb.mkdir(exist_ok=True)
    ziel = korb / f"{datetime.now():%Y%m%d-%H%M%S}-{pfad.name}"
    pfad.replace(ziel)
    return ziel.name


def _vorhandene_termine(termine_dir: Path) -> set:
    from study_agent.pipeline.termine import TZ, load_termine
    events, _ = load_termine(termine_dir)
    return {(e.name, e.due.astimezone(TZ).date().isoformat()) for e in events}


def pruefungsplan_lesen(project_dir: Path, data_dir: Path, name: str) -> Dict[str, Any]:
    pfad = studium_datei(project_dir, name)
    if pfad.suffix.lower() != ".xlsx":
        raise ValueError("Der Prüfungsplan muss eine Excel-Datei (.xlsx) sein")
    pruefungen = pruefungsplan.lesen(pfad)
    module = module_lib.moodle_kurse(data_dir) + module_lib.eigene_module(data_dir)
    v = pruefungsplan.vorschlag(pruefungen, module)
    vorhanden = _vorhandene_termine(project_dir / "termine")
    return {
        "datei": pfad.name,
        "module": module,
        "ohne_modul": OHNE_MODUL,
        "studiengang": v["studiengang"],
        "studiengaenge": sorted({p.studiengang for p in pruefungen if p.studiengang}),
        "pruefungen": [
            p.als_dict() | {
                "titel": p.titel(),
                "vorschlag": v["zuordnung"][p.index],
                "vorhanden": (p.titel(), p.datum.isoformat()) in vorhanden,
            }
            for p in pruefungen
        ],
    }


def pruefungsplan_importieren(project_dir: Path, data_dir: Path, name: str,
                              eintraege: List[Dict[str, Any]]) -> Dict[str, Any]:
    from study_agent.server.dashboard.routes_calendar import add_termin

    pfad = studium_datei(project_dir, name)
    pruefungen = {p.index: p for p in pruefungsplan.lesen(pfad)}
    erlaubt = set(module_lib.moodle_kurse(data_dir) + module_lib.eigene_module(data_dir)) | {OHNE_MODUL}
    termine_dir = project_dir / "termine"
    vorhanden = _vorhandene_termine(termine_dir)
    neu, doppelt = [], []
    for e in eintraege:
        p = pruefungen.get(e.get("index"))
        modul = str(e.get("modul") or "")
        if p is None:
            raise ValueError(f"Prüfung {e.get('index')!r} gibt es im Plan nicht")
        if modul not in erlaubt:
            raise ValueError(f"Modul {modul!r} unbekannt")
        if (p.titel(), p.datum.isoformat()) in vorhanden:
            doppelt.append(p.index)
            continue
        add_termin(modul, p.termin(pfad.name), termine_dir)
        vorhanden.add((p.titel(), p.datum.isoformat()))
        neu.append({"index": p.index, "modul": modul, "datum": p.datum.isoformat(), "titel": p.titel()})
    return {"neu": neu, "schon_vorhanden": doppelt}


def module_uebersicht(project_dir: Path, data_dir: Path, state_dir: Path, cached_study: Callable,
                      calendar_events: Callable) -> List[Dict[str, Any]]:
    from study_agent.config import Settings
    from study_agent.pipeline.quellen import quellen_modul
    from study_agent.server.dashboard.routes_modul import get_modul_data

    settings = Settings(data_dir=data_dir, project_dir=project_dir)
    e = einstellungen.laden(state_dir)
    ignoriert = set(e["filter"]["kurse_ignorieren"])
    archiv = set(e["semester"]["archiv"])
    eigene = module_lib.eigene_module(data_dir)
    lernen = project_dir / "lernen"
    verarbeitet = {p.name for p in lernen.iterdir() if p.is_dir()} if lernen.is_dir() else set()
    namen = sorted(set(module_lib.moodle_kurse(data_dir)) | set(eigene) | verarbeitet)
    events = calendar_events(days=200) or []
    heute = date.today().isoformat()
    out = []
    for name in namen:
        d = get_modul_data(name, project_dir, cached_study, lambda days=120: events)
        kommend = [ev for ev in d["termine"] if str(ev.get("due") or "")[:10] >= heute]
        pruefung = next((ev for ev in kommend if ev.get("kind") == "pruefung"), None)
        naechster = next((ev for ev in kommend if ev.get("kind") not in ("lektion",)), None)
        out.append({
            "name": name,
            "quelle": module_lib.QUELLE_EIGENE if name in eigene else module_lib.QUELLE_MOODLE,
            "ignoriert": name in ignoriert,
            "archiviert": name in archiv,
            "fortschritt": d["fortschritt"]["gesamt"],
            "pruefung": pruefung,
            "naechster_termin": naechster,
            "dateien_eigene": len(module_lib.dateien(data_dir, name)),
            "leistungsnachweis": d["leistungsnachweis"].get("art"),
            "quellen": quellen_modul(settings, name)["zusammenfassung"]["nutzt"],
        })
    return out


def _pruefungsdatum(termine: List[Dict[str, Any]], heute: str) -> date | None:
    for ev in termine:
        tag = str(ev.get("due") or ev.get("date") or "")[:10]
        if ev.get("kind") == "pruefung" and tag >= heute:
            return date.fromisoformat(tag)
    return None


def lernplan_daten(project_dir: Path, data_dir: Path, state_dir: Path, cached_study: Callable,
                   calendar_events: Callable, heute: date | None = None) -> Dict[str, Any]:
    """Lernplan aller nicht archivierten Module mit Prüfungsdatum, plus Module ohne Datum."""
    from study_agent.server.dashboard.routes_karten import get_course_cards
    from study_agent.server.dashboard.routes_modul import get_modul_data

    heute = heute or date.today()
    archiv = set(einstellungen.laden(state_dir)["semester"]["archiv"])
    erledigt = lernplan.laden(state_dir)
    lernen = project_dir / "lernen"
    verarbeitet = {p.name for p in lernen.iterdir() if p.is_dir()} if lernen.is_dir() else set()
    namen = sorted((set(module_lib.moodle_kurse(data_dir)) | set(module_lib.eigene_module(data_dir)) | verarbeitet)
                   - archiv)
    events = calendar_events(days=365) or []
    plaene, module, ohne = {}, [], []
    for name in namen:
        d = get_modul_data(name, project_dir, cached_study, lambda days=120: events)
        termine = sorted(d["termine"], key=lambda ev: str(ev.get("due") or ""))
        pruefung = _pruefungsdatum(termine, heute.isoformat())
        index = project_dir / "knowledge" / name / "INDEX.md"
        ordnung = lernplan.reihenfolge(index.read_text(errors="replace")) if index.is_file() else None
        themen = lernplan.themen_aus_wochen(d["fortschritt"]["wochen"], ordnung)
        if pruefung is None:
            ohne.append({"name": name, "leistungsnachweis": d["leistungsnachweis"].get("art"), "themen": len(themen)})
            continue
        fertig = set(erledigt.get(name, []))
        plaene[name] = lernplan.modul_plan(themen, pruefung, heute, fertig)
        module.append({
            "name": name,
            "pruefung": pruefung.isoformat(),
            "tage": (pruefung - heute).days,
            "themen": [{"id": t.id, "name": t.name, "aufbereitet": t.aufbereitet, "erledigt": t.id in fertig}
                       for t in themen],
            "karten": lernplan.karten_stand(get_course_cards(name, lernen, state_dir)),
        })
    module.sort(key=lambda m: m["pruefung"])
    return {"heute": heute.isoformat(), "woche": lernplan.plan_start(heute).isoformat(),
            "wochen": lernplan.zusammenfuehren(plaene), "module": module, "ohne_pruefung": ohne}


def semester_daten(project_dir: Path, data_dir: Path, state_dir: Path, cached_study: Callable) -> Dict[str, Any]:
    """Für den Semesterwechsel: welche Module aktuell in Moodle laufen, welche archiviert sind."""
    archiv = set(einstellungen.laden(state_dir)["semester"]["archiv"])
    try:
        aktuell = {c.get("name") for c in cached_study("courses", "--current", "--json") or [] if isinstance(c, dict)}
    except Exception:
        aktuell = set()
    moodle = module_lib.moodle_kurse(data_dir)
    eigene = module_lib.eigene_module(data_dir)
    lernen = project_dir / "lernen"
    verarbeitet = {p.name for p in lernen.iterdir() if p.is_dir()} if lernen.is_dir() else set()
    out = []
    for name in sorted(set(moodle) | set(eigene) | verarbeitet | archiv):
        quelle = module_lib.QUELLE_EIGENE if name in eigene else module_lib.QUELLE_MOODLE
        laeuft = name in aktuell
        out.append({"name": name, "quelle": quelle, "aktuell": laeuft, "archiviert": name in archiv,
                    # Vorschlag: Moodle-Kurse, die Moodle nicht mehr als laufend führt
                    "vorschlag_archiv": quelle == module_lib.QUELLE_MOODLE and bool(aktuell) and not laeuft})
    neu = sorted(n for n in aktuell if n and n not in set(moodle))
    return {"module": out, "neu_in_moodle": neu, "moodle_bekannt": bool(aktuell)}


def archiv_setzen(state_dir: Path, archiv: List[str]) -> List[str]:
    e = einstellungen.laden(state_dir)
    e["semester"]["archiv"] = archiv
    return einstellungen.speichern(state_dir, e)["semester"]["archiv"]


def register_routes(router: Any, get_settings_fn: Any, cached_study: Callable, calendar_events: Callable,
                    cache_invalidate_fn: Callable) -> None:
    from fastapi import Body, File, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse

    def fehler(exc: Exception):
        return HTTPException(400, str(exc))

    def _modulnamen(s) -> List[str]:
        lernen = s.project_dir / "lernen"
        verarbeitet = {p.name for p in lernen.iterdir() if p.is_dir()} if lernen.is_dir() else set()
        return sorted(set(module_lib.moodle_kurse(s.data_dir)) | set(module_lib.eigene_module(s.data_dir)) | verarbeitet)

    @router.get("/modulfarben")
    def get_modulfarben():
        s = get_settings_fn()
        return {"farben": modulfarben.farben(s.state_dir, _modulnamen(s)), "palette": modulfarben.PALETTE}

    @router.put("/modulfarben")
    def put_modulfarbe(payload: Dict[str, Any] = Body(...)):
        s = get_settings_fn()
        farbe = payload.get("farbe")
        try:
            out = modulfarben.setzen(s.state_dir, str(payload.get("name") or ""),
                                     None if farbe in (None, "") else str(farbe), _modulnamen(s))
        except ValueError as exc:
            raise fehler(exc) from exc
        return {"farben": out, "palette": modulfarben.PALETTE}

    @router.get("/module")
    def get_module():
        s = get_settings_fn()
        return {"module": module_uebersicht(s.project_dir, s.data_dir, s.state_dir, cached_study, calendar_events)}

    @router.post("/module")
    def post_modul(payload: Dict[str, Any] = Body(...)):
        s = get_settings_fn()
        try:
            name = module_lib.modul_anlegen(s.data_dir, str(payload.get("name") or ""))
        except (ValueError, OSError) as exc:
            raise fehler(exc) from exc
        cache_invalidate_fn("courses", "files_tree")
        return {"name": name}

    @router.delete("/module")
    def delete_modul(name: str = Query(...)):
        s = get_settings_fn()
        try:
            module_lib.modul_entfernen(s.data_dir, name)
        except (ValueError, OSError) as exc:
            raise fehler(exc) from exc
        cache_invalidate_fn("courses", "files_tree")
        return {"entfernt": name}

    @router.get("/studium")
    def get_studium():
        return {"dateien": studium_liste(get_settings_fn().project_dir)}

    @router.post("/studium/upload")
    async def post_studium_upload(file: UploadFile = File(...)):
        daten = await file.read()
        try:
            name = studium_speichern(get_settings_fn().project_dir, file.filename or "", daten)
        except ValueError as exc:
            raise fehler(exc) from exc
        return {"name": name}

    @router.get("/studium/datei")
    def get_studium_datei(name: str = Query(...)):
        try:
            pfad = studium_datei(get_settings_fn().project_dir, name)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(pfad, filename=pfad.name)

    @router.delete("/studium/datei")
    def delete_studium_datei(name: str = Query(...)):
        try:
            return {"papierkorb": studium_entfernen(get_settings_fn().project_dir, name)}
        except ValueError as exc:
            raise fehler(exc) from exc

    @router.get("/pruefungsplan")
    def get_pruefungsplan(datei: str = Query(...)):
        s = get_settings_fn()
        try:
            return pruefungsplan_lesen(s.project_dir, s.data_dir, datei)
        except ValueError as exc:
            raise fehler(exc) from exc

    @router.get("/lernplan")
    def get_lernplan():
        s = get_settings_fn()
        return lernplan_daten(s.project_dir, s.data_dir, s.state_dir, cached_study, calendar_events)

    @router.post("/lernplan/thema")
    def post_lernplan_thema(payload: Dict[str, Any] = Body(...)):
        modul, thema = str(payload.get("modul") or ""), str(payload.get("thema") or "")
        if not modul or not thema:
            raise HTTPException(400, "modul und thema fehlen")
        return {"erledigt": lernplan.erledigt_setzen(get_settings_fn().state_dir, modul, thema,
                                                     bool(payload.get("erledigt")))}

    @router.get("/semester")
    def get_semester():
        s = get_settings_fn()
        return semester_daten(s.project_dir, s.data_dir, s.state_dir, cached_study)

    @router.put("/semester/archiv")
    def put_semester_archiv(payload: Dict[str, Any] = Body(...)):
        try:
            archiv = archiv_setzen(get_settings_fn().state_dir, payload.get("archiv"))
        except ValueError as exc:
            raise fehler(exc) from exc
        cache_invalidate_fn("pending", "courses")
        return {"archiv": archiv}

    @router.post("/pruefungsplan/import")
    def post_pruefungsplan_import(payload: Dict[str, Any] = Body(...)):
        s = get_settings_fn()
        eintraege = payload.get("eintraege")
        if not isinstance(eintraege, list) or not eintraege:
            raise HTTPException(400, "Keine Prüfungen ausgewählt")
        try:
            out = pruefungsplan_importieren(s.project_dir, s.data_dir, str(payload.get("datei") or ""), eintraege)
        except ValueError as exc:
            raise fehler(exc) from exc
        cache_invalidate_fn("termine")
        return out
