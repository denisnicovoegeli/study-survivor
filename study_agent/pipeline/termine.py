import re
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from study_agent.pipeline.moodle_api import Deadline

TZ = ZoneInfo("Europe/Zurich")
KINDS = frozenset({"abgabe", "pruefung", "praesentation", "meilenstein", "praesenz", "ausfall", "lektion", "termin"})
DEDUP_KINDS = frozenset({"abgabe", "pruefung"})
_FULLWIDTH = str.maketrans("⧸：｜？＜＞＂", "/:|?<>\"")


def _norm(course: str) -> str:
    return course.translate(_FULLWIDTH).casefold().strip()


def _day(d: Deadline) -> date:
    return d.due.astimezone(TZ).date()


def _to_deadline(course: str, course_id: int, entry: dict, fallback_source: str) -> Deadline:
    day = entry.get("datum")
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValueError(f"datum muss JJJJ-MM-TT sein, nicht {day!r}")
    title = str(entry.get("titel") or "").strip()
    if not title:
        raise ValueError("titel fehlt")
    kind = entry.get("art", "termin")
    if kind not in KINDS:
        raise ValueError(f"art {kind!r} unbekannt, erlaubt: {', '.join(sorted(KINDS))}")
    zeit = entry.get("zeit")
    if isinstance(zeit, int):  # YAML 1.1 liest ein unquotiertes 13:00 als 780 (Sexagesimalzahl)
        zeit = f"{zeit // 60:02d}:{zeit % 60:02d}"
    clock = time(23, 59) if zeit is None else time.fromisoformat(str(zeit))
    return Deadline(
        course=course,
        name=title,
        due=datetime.combine(day, clock, TZ).astimezone(timezone.utc),
        url="",
        kind=kind,
        overdue=False,
        source=str(entry.get("quelle") or fallback_source),
        all_day=zeit is None,
        course_id=course_id,
    )


def load_termine(termine_dir: Path) -> tuple[list[Deadline], list[str]]:
    events: list[Deadline] = []
    errors: list[str] = []
    for path in sorted(termine_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text()) or {}
            course = str(raw["kurs"])
            course_id = int(raw.get("kurs_id") or 0)
            entries = raw.get("termine") or []
        except Exception as exc:  # YAML-Syntax, fehlender Kurs, falscher Typ
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}"[:200])
            continue
        for i, entry in enumerate(entries, start=1):
            try:
                events.append(_to_deadline(course, course_id, entry, path.name))
            except Exception as exc:
                errors.append(f"{path.name} Eintrag {i}: {exc}"[:200])
    return events, errors


# Reihenfolge, nach der beim Zusammenführen die Art gewählt wird (wichtigste zuerst)
WICHTIGKEIT = ("ausfall", "pruefung", "abgabe", "praesentation", "praesenz", "meilenstein", "termin", "lektion")
_TEILE = re.compile(r"\s*[;,:–—]\s*|\s+-\s+")
_REST = re.compile(r"\s*[;–—]\s*|\s+-\s+")
_FUELLWOERTER = frozenset({"und", "der", "die", "das", "des", "den", "von", "vor", "mit", "im", "in", "am", "an",
                           "eines", "einer", "ein", "eine", "für", "zu", "zum", "zur"})


def _kern(titel: str) -> str:
    """Titel bis zum ersten Trenner, vereinheitlicht («&» = «und»)."""
    t = titel.translate(_FULLWIDTH).casefold().replace("&", "und")
    return re.sub(r"\s+", " ", _TEILE.split(t, maxsplit=1)[0]).strip()


def _woerter(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold().replace("&", "und"))) - _FUELLWOERTER


def gleicher_termin(a: Deadline, b: Deadline) -> bool:
    """Gleiches Modul, gleicher Zeitpunkt und gleicher Kern im Titel (z. B. aus Semesterprogramm und Plan)."""
    if _norm(a.course) != _norm(b.course) or a.due != b.due or a.all_day != b.all_day:
        return False
    ka, kb = _kern(a.name), _kern(b.name)
    return bool(ka) and (ka == kb or SequenceMatcher(None, ka, kb).ratio() >= 0.85)


def _verbinden(a: Deadline, b: Deadline) -> Deadline:
    lang, kurz = (a, b) if len(a.name) >= len(b.name) else (b, a)
    # Teile des kürzeren Titels, die etwas Neues sagen (z. B. «Gruppen 4 und 9»), hinten anhängen
    bekannt = _woerter(lang.name)
    rest = _TEILE.split(kurz.name, maxsplit=1)[1:]  # alles nach dem Kern
    teile = _REST.split(rest[0]) if rest else []     # Kommas bleiben drin («Gruppen 1, 2 und 5»)
    extra = [t for t in teile if t.strip() and not _woerter(t) <= bekannt]
    name = lang.name + "".join(f" · {t.strip()}" for t in extra)
    art = min((a.kind, b.kind), key=lambda k: WICHTIGKEIT.index(k) if k in WICHTIGKEIT else len(WICHTIGKEIT))
    quellen = []
    for q in (a.source, b.source):
        for teil in q.split("; "):
            if teil and teil not in quellen:
                quellen.append(teil)
    return replace(lang, name=name, kind=art, source="; ".join(quellen), titel_original=lang.titel_original or lang.name)


def zusammenfuehren(events: list[Deadline]) -> list[Deadline]:
    """Doppelte Termine aus verschiedenen Quellen zu einem Eintrag verbinden."""
    out: list[Deadline] = []
    gruppen: dict[tuple, list[int]] = {}
    for e in sorted(events, key=lambda e: e.due):
        key = (_norm(e.course), e.due, e.all_day)
        for i in gruppen.get(key, []):
            if gleicher_termin(out[i], e):
                out[i] = _verbinden(out[i], e)
                break
        else:
            gruppen.setdefault(key, []).append(len(out))
            out.append(e)
    return out


def upcoming_termine(events: list[Deadline], now: datetime, days: int, vergangen: int = 0) -> list[Deadline]:
    """Termine von `vergangen` Tagen zurück bis `days` Tage voraus (Kalender zeigt auch vergangene Tage)."""
    start, end = now - timedelta(days=vergangen), now + timedelta(days=days)
    return sorted((e for e in events if start <= e.due <= end), key=lambda e: e.due)


def merge_deadlines(moodle: list[Deadline], local: list[Deadline]) -> list[Deadline]:
    by_id = {(d.course_id, _day(d)) for d in moodle if d.course_id}
    by_name = {(_norm(d.course), _day(d)) for d in moodle}

    def duplicate(d: Deadline) -> bool:
        if d.kind not in DEDUP_KINDS:
            return False
        if d.course_id and (d.course_id, _day(d)) in by_id:
            return True
        return (_norm(d.course), _day(d)) in by_name

    return sorted([*moodle, *(d for d in local if not duplicate(d))], key=lambda d: d.due)
