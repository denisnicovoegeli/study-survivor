import json
import re
import shutil
import subprocess
import uuid
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

from study_agent.pipeline.classify import load_overrides
from study_agent.config import Settings
from study_agent.pipeline.eigene import advance_eigene_state, eigene_files, eigene_new_files
from study_agent.pipeline.moodle_api import Deadline, MoodleClient, MoodleError
from study_agent.pipeline.moodle_db import (FileRecord, all_files, current_courses, files_since, max_file_id,
                                   read_last_file_id, write_last_file_id)
from study_agent.pipeline.pending import PendingFile, pending_files
from study_agent.pipeline.termine import load_termine, merge_deadlines, upcoming_termine, zusammenfuehren

TZ = ZoneInfo("Europe/Zurich")
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
URGENT = timedelta(days=3)
MAX_PENDING_LINES = 10


def _fmt_due(d: Deadline) -> str:
    local = d.due.astimezone(TZ)
    clock = "" if d.all_day else f" {local:%H:%M}"
    return f"{WEEKDAYS[local.weekday()]} {local:%d.%m.}{clock}"


def _deadline_line(d: Deadline) -> str:
    link = f" ([Link]({d.url}))" if d.url else ""
    origin = f" _({d.kind} · {d.source})_" if d.source else ""
    return f"- **{_fmt_due(d)}** · {d.course} — {d.name}{link}{origin}"


def _file_line(f: FileRecord, site_url: str) -> str:
    if getattr(f, "quelle", "") == "eigene":
        return f"- {f.name} · {f.modified.astimezone(TZ):%d.%m.} · eigene"
    updated = " (aktualisiert)" if f.updated else ""
    moodle = f" · [Moodle]({f.moodle_link(site_url)})" if site_url else ""
    return f"- {f.section} / {f.name}{updated} · {f.modified.astimezone(TZ):%d.%m.}{moodle}"


def _pending_lines(pending: list[PendingFile]) -> list[str]:
    counts = {route: sum(p.route == route for p in pending) for route in ("voll", "info", "fragen")}
    lines = ["", "## Zu verarbeiten",
             f"{len(pending)} Dateien ({counts['voll']} Folien, {counts['info']} Semesterprogramm/Projekt,"
             f" {counts['fragen']} unklar) → in Claude Code `/verarbeiten`"]
    for p in pending[:MAX_PENDING_LINES]:
        details = ", ".join(x for x in (p.klasse, f"{p.pages} S." if p.pages else "",
                                        "veraltet" if p.reason == "veraltet" else "") if x)
        lines.append(f"- {p.course} / {p.name} ({details})")
    if len(pending) > MAX_PENDING_LINES:
        lines.append(f"- … und {len(pending) - MAX_PENDING_LINES} weitere (`uv run study pending`)")
    return lines


def render_briefing(today: date, deadlines: list[Deadline] | None, new_files: list[FileRecord], now: datetime, *,
                    error: str | None = None, baseline: bool = False, pending: list[PendingFile] | None = None,
                    config_errors: list[str] | None = None, no_termine: bool = False, site_url: str = "") -> str:
    lines = [f"# Briefing {WEEKDAYS_LONG[today.weekday()]}, {today:%d.%m.%Y}", ""]
    if error:
        lines += [f"> ⚠️ Moodle-API nicht erreichbar: {error}", ""]
    if no_termine:
        lines += ["> Noch keine Termine aus Semesterprogrammen erfasst. In Claude Code `/verarbeiten` ausführen.", ""]
    if deadlines is not None:
        overdue = [d for d in deadlines if d.overdue or d.due < now]
        upcoming = [d for d in deadlines if d not in overdue]
        if overdue:
            lines += ["## Überfällig", *map(_deadline_line, overdue), ""]
        lines += ["## Fällig", *(map(_deadline_line, upcoming) if upcoming else ["_Keine._"]), ""]
    lines += ["## Neue Dateien"]
    if baseline:
        lines += ["_Erster Lauf: Basislinie gesetzt, ab morgen erscheinen hier neue Dateien._"]
    elif not new_files:
        lines += ["_Keine._"]
    else:
        for course, files in groupby(new_files, key=lambda f: f.course):
            lines += ["", f"### {course}", *(_file_line(f, site_url) for f in files)]
    if pending:
        lines += _pending_lines(pending)
    if config_errors:
        lines += ["", "## Fehler in termine/ oder klassen.yaml", *(f"- ⚠️ {e}" for e in config_errors)]
    return "\n".join(lines) + "\n"


def summary_line(deadlines: list[Deadline] | None, new_files: list[FileRecord], now: datetime, error: str | None,
                 pending_count: int = 0) -> str:
    files_part = f"{len(new_files)} neue Dateien" + (f" · {pending_count} zu verarbeiten" if pending_count else "")
    if error:
        return f"⚠️ Moodle-API: {error} · {files_part}"
    urgent = [d for d in deadlines or [] if d.due <= now + URGENT]
    word = "Deadline" if len(urgent) == 1 else "Deadlines"
    return f"{len(urgent)} {word} in ≤3 Tagen · {files_part}"


def run_briefing(settings: Settings, client: MoodleClient, site_url: str, now: datetime | None = None,
                 days: int = 14, info: dict | None = None) -> tuple[Path, str]:
    """Schreibt das Briefing des Tages. info (optional) bekommt neue Dateien, Fristen und Fehler für Mitteilungen."""
    now = now or datetime.now(timezone.utc)
    moodle, error = None, None
    try:
        moodle = client.upcoming_deadlines(days=days, now=now)
    except MoodleError as exc:
        error = exc.errorcode or str(exc)
    all_termine, termine_errors = load_termine(settings.termine_dir)
    local = zusammenfuehren(upcoming_termine(all_termine, now, days))
    deadlines = merge_deadlines(moodle or [], local) if moodle is not None or local else None

    db = settings.moodle_db
    last = read_last_file_id(settings.state_dir)
    newest = max_file_id(db)
    baseline = last is None
    files = [] if baseline else files_since(db, last)
    files = [*files, *eigene_new_files(settings.data_dir, settings.state_dir)]
    today = now.astimezone(TZ).date()
    overrides, klassen_errors = load_overrides(settings.klassen_path)
    current = {c.course_id for c in current_courses(db, today)}
    pending = pending_files(settings, all_files(db), overrides, site_url, current,
                            eigene=eigene_files(settings.data_dir))

    settings.briefings_dir.mkdir(parents=True, exist_ok=True)
    path = settings.briefings_dir / f"{today:%Y-%m-%d}.md"
    path.write_text(render_briefing(
        today, deadlines, files, now, error=error, baseline=baseline, pending=pending,
        config_errors=termine_errors + klassen_errors, no_termine=not any(settings.termine_dir.glob("*.yaml")),
        site_url=site_url))
    write_last_file_id(settings.state_dir, newest)
    advance_eigene_state(settings.data_dir, settings.state_dir)
    create_briefing_suggestions(settings, pending)
    if info is not None:
        info.update(neue_dateien=len(files), fehler=error,
                    fristen=[(f"{d.course}: {d.name}" if d.course else d.name, d.due)
                             for d in deadlines or [] if not d.overdue])
    return path, summary_line(deadlines, files, now, error, len(pending))


def create_briefing_suggestions(settings: Settings, pending: list[PendingFile]) -> list[dict]:
    """Legt Vorschläge im Auftragsbrett (state/studium-kanban.json) an, z.B. 'W07 verarbeiten', ohne Duplikate."""
    if not pending:
        return []

    kanban_path = settings.state_dir / "studium-kanban.json"
    cards = []
    if kanban_path.is_file():
        try:
            raw = json.loads(kanban_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("cards"), list):
                cards = raw["cards"]
        except (OSError, json.JSONDecodeError):
            cards = []

    existing_keys = {c.get("source_key") for c in cards if c.get("source_key")}

    # Nach Kurs und Abschnitt gruppieren
    by_course_sec: dict[tuple[str, str], list[PendingFile]] = {}
    for p in pending:
        key = (p.course, p.section)
        by_course_sec.setdefault(key, []).append(p)

    added = []
    for (course, section), files in by_course_sec.items():
        w_match = re.search(r"(?:Woche|W)\s*0?(\d+)", section, re.IGNORECASE)
        w_tag = f"W{int(w_match.group(1)):02d}" if w_match else section or "Woche"
        source_key = f"pending:{course}:{section}"
        if source_key in existing_keys:
            continue
        if any(f"pending:{f.rel}" in existing_keys for f in files):
            continue

        card = {
            "id": uuid.uuid4().hex[:12],
            "title": f"{w_tag} verarbeiten",
            "column": "vorschlaege",
            "skill": "verarbeiten",
            "args": [course, section],
            "course": course,
            "detail": f"{len(files)} offene Datei(en) in {section}",
            "source_key": source_key,
            "note": "",
            "session_link": None,
            "created_files": [],
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        cards.append(card)
        existing_keys.add(source_key)
        added.append(card)

    if added:
        kanban_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = kanban_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(kanban_path)

    return added


def notify(title: str, message: str) -> None:
    # macOS-Benachrichtigung. Auf Linux/Container gibt es osascript nicht:
    # dort ist Benachrichtigen ein No-op (das Briefing geht per Telegram).
    if not shutil.which("osascript"):
        return
    script = (f"display notification {json.dumps(message, ensure_ascii=False)}"
              f" with title {json.dumps(title, ensure_ascii=False)}")
    subprocess.run(["osascript", "-e", script], check=False)
