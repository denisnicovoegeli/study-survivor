import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone, date
from pathlib import Path

from study_agent.pipeline.briefing import TZ, notify, run_briefing
from study_agent.pipeline.classify import load_overrides, set_override
from study_agent.config import load_moodle_config, load_settings
from study_agent.pipeline.convert import (convert_tree, folien_path, load_manifest, markitdown_converter, meta_from_records,
                                 write_course_indexes)
from study_agent.pipeline.eigene import eigene_files, eigene_new_files, save_eigene_file
from study_agent.pipeline.moodle_api import MoodleClient, MoodleError
from study_agent.pipeline.moodle_db import MoodleDbError, all_files, courses, current_courses, files_since, read_last_file_id
from study_agent.pipeline.pending import check_folien, finish, pending_files
from study_agent.pipeline.suche import (build_index, index_db_path, moodle_links, search, treffer_json)
from study_agent.pipeline.termine import load_termine, upcoming_termine


def _site_url(settings) -> str:
    return load_moodle_config(settings.moodle_config_path).site_url


def _client(settings) -> MoodleClient:
    return MoodleClient(load_moodle_config(settings.moodle_config_path))


def _current_ids(settings) -> set[int]:
    return {c.course_id for c in current_courses(settings.moodle_db, datetime.now(TZ).date())}


def _print_json(items) -> None:
    print(json.dumps([asdict(i) for i in items], default=str, ensure_ascii=False, indent=2))


def _overrides(settings) -> dict[str, str]:
    overrides, errors = load_overrides(settings.klassen_path)
    for e in errors:
        print(f"FEHLER {e}", file=sys.stderr)
    return overrides


def cmd_deadlines(args, settings) -> int:
    deadlines = _client(settings).upcoming_deadlines(days=args.days)
    if args.json:
        _print_json(deadlines)
    else:
        for d in deadlines:
            print(f"{d.due:%Y-%m-%d %H:%M}Z  {'ÜBERFÄLLIG ' if d.overdue else ''}{d.course} — {d.name}")
    return 0


def cmd_termine(args, settings) -> int:
    events, errors = load_termine(settings.termine_dir)
    events = upcoming_termine(events, datetime.now(timezone.utc), args.days)
    if args.json:
        _print_json(events)
    else:
        for d in events:
            when = d.due.astimezone(TZ).strftime("%Y-%m-%d" if d.all_day else "%Y-%m-%d %H:%M")
            print(f"{when:<16}  {d.kind:<13} {d.course} — {d.name}  [{d.source}]")
    for e in errors:
        print(f"FEHLER {e}", file=sys.stderr)
    return 1 if errors else 0


def cmd_grades(args, settings) -> int:
    grades = _client(settings).course_grades()
    if args.json:
        _print_json(grades)
    else:
        for g in grades:
            print(f"{g.grade:>6}  {g.course}")
    return 0


def cmd_new_files(args, settings) -> int:
    moodle = files_since(settings.moodle_db, read_last_file_id(settings.state_dir) or 0)
    files = [*moodle, *eigene_new_files(settings.data_dir, settings.state_dir)]
    if args.json:
        _print_json(files)
    else:
        for f in files:
            if getattr(f, "quelle", "") == "eigene":
                print(f"{f.modified.astimezone(TZ):%Y-%m-%d}  {f.course} / {f.name}  [eigene]")
            else:
                print(f"{f.modified.astimezone(TZ):%Y-%m-%d}  {f.course} / {f.section} / {f.name}")
    return 0


def cmd_courses(args, settings) -> int:
    items = current_courses(settings.moodle_db, datetime.now(TZ).date()) if args.current else courses(settings.moodle_db)
    if args.json:
        _print_json(items)
    else:
        for c in items:
            print(f"{c.last_modified.astimezone(TZ):%Y-%m-%d}  {c.course_id:>6}  {c.files:>4} Dateien  {c.name}")
    return 0


def cmd_convert(args, settings) -> int:
    site = _site_url(settings)
    records = all_files(settings.moodle_db)
    folders = None
    if args.current:
        ids = _current_ids(settings)
        folders = {rel.parts[0] for r in records if r.course_id in ids and (rel := r.rel(settings.data_dir))}
    report = convert_tree(settings.data_dir, settings.knowledge_dir, markitdown_converter(), force=args.force,
                          course_filter=args.course, courses=folders,
                          meta=meta_from_records(records, settings.data_dir, site))
    write_course_indexes(settings.knowledge_dir, settings.data_dir, records, site, _overrides(settings))
    print(f"konvertiert: {len(report.converted)} · unverändert: {report.skipped} · fehlgeschlagen: {len(report.failed)}")
    for key, reason in report.failed:
        print(f"  ✗ {key}: {reason}")
    sys.stdout.flush()
    sys.stderr.flush()
    # markitdown 0.1.8 crashes during interpreter shutdown (libc++abi recursive_mutex); skip teardown.
    os._exit(0)


def cmd_pending(args, settings) -> int:
    ids = None if args.all else _current_ids(settings)
    items = pending_files(settings, all_files(settings.moodle_db), _overrides(settings), _site_url(settings), ids,
                          eigene=eigene_files(settings.data_dir))
    if args.json:
        _print_json(items)
    else:
        for p in items:
            print(f"{p.route:<6} {p.klasse:<16} {p.reason:<8} {p.rel}")
    return 0


def cmd_check_folien(args, settings) -> int:
    entry = load_manifest(settings.knowledge_dir).get(args.rel)
    if not entry or not entry.get("seiten"):
        print(f"FEHLER {args.rel}: nicht im Manifest oder Seitenzahl unbekannt", file=sys.stderr)
        return 1
    missing = check_folien(folien_path(settings.knowledge_dir, Path(args.rel)), entry["seiten"])
    print(f"fehlende Folien: {missing}" if missing else f"vollständig: {entry['seiten']} Folien")
    return 1 if missing else 0


def cmd_done(args, settings) -> int:
    try:
        finish(settings, args.rel, _overrides(settings))
    except ValueError as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return 1
    print(f"verarbeitet: {args.rel}")
    return 0


def cmd_klasse(args, settings) -> int:
    try:
        set_override(settings.klassen_path, args.rel, args.klasse)
    except ValueError as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return 1
    print(f"{args.rel}: {args.klasse}")
    return 0


def cmd_eigene_upload(args, settings) -> int:
    """Speichert eine eigene Datei (Teams-Material) nach _eigene/<Kurs>/<Datei>."""
    path = Path(args.file)
    if not path.is_file():
        print(f"FEHLER: {args.file}: Datei nicht gefunden", file=sys.stderr)
        return 1
    try:
        dest = save_eigene_file(settings.data_dir, args.course, path.name, path.read_bytes())
    except ValueError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(
            {"course": dest.parent.name, "name": dest.name,
             "rel": dest.relative_to(settings.data_dir).as_posix()}, ensure_ascii=False))
    else:
        print(f"gespeichert: {dest.relative_to(settings.data_dir)}")
    return 0


def cmd_index(args, settings) -> int:
    report = build_index(settings.knowledge_dir, settings.state_dir, force=args.force,
                         links=moodle_links(settings))
    print(f"indexiert: {len(report.indexed)} · unverändert: {report.skipped} · entfernt: {len(report.removed)}")
    return 0


def cmd_rag_index(args, settings) -> int:
    from study_agent.agent.rag import build_dense_index
    report = build_dense_index(settings, force=args.force, kurs=args.course)
    print(f"Chunks: {report['chunks']} · neu eingebettet: {report['neu']} · entfernt: {report['entfernt']}")
    return 0


def cmd_ask(args, settings) -> int:
    import asyncio
    from study_agent.agent.cli_chat import run_ask
    return asyncio.run(run_ask(args))


def cmd_verarbeiten(args, settings) -> int:
    from study_agent.agent.cli_verarbeiten import cmd_verarbeiten as run
    return run(args, settings)


def cmd_freigabe(args, settings) -> int:
    from study_agent.agent.cli_verarbeiten import cmd_freigabe as run
    return run(args, settings)


def cmd_suche(args, settings) -> int:
    hits = search(index_db_path(settings.state_dir), args.frage, course=args.course, limit=args.limit)
    if args.json:
        print(treffer_json(hits))
    elif not hits:
        print("Keine Treffer.")
    else:
        for h in hits:
            art = "Folie" if h.quelle == "folien" else "Seite"
            print(f"{h.kurs} — {Path(h.datei).name} · {art} {h.folie}")
            print(f"  {h.text[:200].replace(chr(10), ' ')}")
            if h.moodle:
                print(f"  {h.moodle}")
    return 0


def cmd_briefing(args, settings) -> int:
    # --print: ganzes Briefing als Markdown auf stdout (z. B. für Telegram), nie eine macOS-Benachrichtigung
    quiet = args.no_notify or args.print
    try:
        path, summary = run_briefing(settings, _client(settings), _site_url(settings), days=args.days)
    except MoodleDbError as exc:
        if not quiet:
            notify("Studium-Briefing", f"⚠️ {exc}")
        raise
    if args.print:
        print(path.read_text(), end="")
    else:
        print(f"{path}\n{summary}")
    if not quiet:
        notify("Studium-Briefing", summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="study")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, *flags):
        p = sub.add_parser(name)
        for flag in flags:
            flag(p)
        p.set_defaults(func=func)

    def days(default):
        return lambda p: p.add_argument("--days", type=int, default=default)

    def switch(name):
        return lambda p: p.add_argument(name, action="store_true")

    def positional(name, **kw):
        return lambda p: p.add_argument(name, **kw)

    add("deadlines", cmd_deadlines, days(14), switch("--json"))
    add("termine", cmd_termine, days(30), switch("--json"))
    add("grades", cmd_grades, switch("--json"))
    add("new-files", cmd_new_files, switch("--json"))
    add("courses", cmd_courses, switch("--current"), switch("--json"))
    add("convert", cmd_convert, lambda p: p.add_argument("--course"), switch("--current"), switch("--force"))
    add("pending", cmd_pending, switch("--all"), switch("--json"))
    add("check-folien", cmd_check_folien, positional("rel"))
    add("done", cmd_done, positional("rel"))
    add("klasse", cmd_klasse, positional("rel"), positional("klasse"))
    add("briefing", cmd_briefing, days(14), switch("--no-notify"), switch("--print"))
    add("eigene-upload", cmd_eigene_upload, lambda p: p.add_argument("--course", required=True),
        positional("file"), switch("--json"))
    add("index", cmd_index, switch("--force"))
    add("rag-index", cmd_rag_index, lambda p: p.add_argument("--course"), switch("--force"))
    add("ask", cmd_ask, positional("frage", nargs="*"), lambda p: p.add_argument("--thread", default="cli"),
        lambda p: p.add_argument("--user", default="stirling"), switch("--json"))
    add("verarbeiten", cmd_verarbeiten, positional("rel", nargs="?"),
        lambda p: p.add_argument("--limit", type=int, default=1), switch("--auto"), switch("--fehler"))
    add("freigabe", cmd_freigabe, positional("thread", nargs="?"),
        lambda p: p.add_argument("--decision", choices=["approve", "edit", "reject"], default="approve"),
        lambda p: p.add_argument("--feedback"), switch("--json"))
    add("suche", cmd_suche, positional("frage"), lambda p: p.add_argument("--course"),
        lambda p: p.add_argument("--limit", type=int, default=5), switch("--json"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        code = args.func(args, load_settings())
    except (MoodleError, MoodleDbError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
