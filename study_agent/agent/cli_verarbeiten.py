"""`study verarbeiten` und `study freigabe`: Graph verarbeiten aus der Kommandozeile."""
import json
import sqlite3
import sys
import time

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from study_agent.agent.verarbeiten import build_verarbeiten_graph, checkpointer_path, open_freigaben, thread_id


def graph():
    con = sqlite3.connect(checkpointer_path(), check_same_thread=False)
    return build_verarbeiten_graph(SqliteSaver(con))


def _run(g, inp, cfg) -> None:
    """Graph ausführen und pro Knoten eine Zeile ausgeben."""
    t0 = time.time()
    for upd in g.stream(inp, cfg, stream_mode="updates"):
        for node, val in upd.items():
            extra = ""
            if node == "check" and isinstance(val, dict):
                p = val.get("pruefung") or {}
                extra = f" ok={p.get('ok')} Beanstandungen={len(p.get('beanstandungen', []))}"
            print(f"  [{time.time() - t0:6.1f}s] {node}{extra}", flush=True)


def _bericht(g, tid: str) -> int:
    st = g.get_state({"configurable": {"thread_id": tid}})
    v = st.values
    if st.next:
        intr = [i.value for t in st.tasks for i in t.interrupts]
        print(f"  FREIGABE nötig (Thread {tid}) nach {v.get('runde')} Runden:")
        for b in (intr[0]["beanstandungen"] if intr else []):
            print(f"    - [{b['art']}] Folie {b['folie']}: {b['beschreibung']}")
        return 3
    if v.get("entscheid") == "reject":
        print("  abgelehnt, Datei bleibt offen")
        return 0
    p = v.get("pruefung") or {}
    print(f"  Runden: {v.get('runde')} · Prüfung ok: {p.get('ok')} · Folien: {len(v.get('folien') or {})}/{len(v.get('texts') or {})}")
    for line in v.get("geschrieben", []):
        print(f"  geschrieben: {line}")
    return 0


def cmd_verarbeiten(args, settings) -> int:
    from study_agent.cli import _current_ids, _overrides, _site_url
    from study_agent.pipeline.eigene import eigene_files
    from study_agent.pipeline.moodle_db import all_files
    from study_agent.pipeline.pending import pending_files

    g = graph()
    if args.rel:
        rels = [args.rel]
    else:
        items = pending_files(settings, all_files(settings.moodle_db), _overrides(settings), _site_url(settings),
                              _current_ids(settings), eigene=eigene_files(settings.data_dir))
        offen = {f["rel"] for f in open_freigaben(g)}
        rels = [p.rel for p in items if p.route in ("voll", "info") and p.rel not in offen][:args.limit]
    code = 0
    for rel in rels:
        tid = thread_id(rel)
        print(f"verarbeiten: {rel}")
        cfg = {"configurable": {"thread_id": tid}}
        try:
            _run(g, {"rel": rel, "sabotage": args.fehler}, cfg)
        except Exception as exc:  # eine Datei darf den Lauf nicht abbrechen
            print(f"  FEHLER {type(exc).__name__}: {exc}", file=sys.stderr)
            code = 1
            continue
        res = _bericht(g, tid)
        if res == 3 and not args.auto and sys.stdin.isatty():
            entscheid = input("  Entscheid (approve/edit/reject, leer = später): ").strip()
            if entscheid:
                fb = input("  Feedback: ").strip() if entscheid == "edit" else ""
                _run(g, Command(resume={"decision": entscheid, "feedback": fb}), cfg)
                res = _bericht(g, tid)
        code = max(code, res)
    return code


def cmd_freigabe(args, settings) -> int:
    g = graph()
    if not args.thread:
        items = open_freigaben(g)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
        for f in items if not args.json else []:
            print(f"{f['thread_id']}  {f['rel']}  ({len(f['beanstandungen'])} Beanstandungen)")
        return 0
    _run(g, Command(resume={"decision": args.decision, "feedback": args.feedback or ""}),
         {"configurable": {"thread_id": args.thread}})
    return _bericht(g, args.thread)
