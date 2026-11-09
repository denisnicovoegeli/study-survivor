from datetime import date, datetime, time, timedelta, timezone
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


def upcoming_termine(events: list[Deadline], now: datetime, days: int) -> list[Deadline]:
    end = now + timedelta(days=days)
    return sorted((e for e in events if now <= e.due <= end), key=lambda e: e.due)


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
