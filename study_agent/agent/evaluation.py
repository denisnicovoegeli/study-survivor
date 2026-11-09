"""`study eval`: Testfragen aus eval/testfragen.yaml gegen den Graphen `chat` laufen lassen (Vorbereitung SW9).

Jede Frage läuft in einem eigenen Thread (eigene SQLite-Datei data/state/eval.sqlite, damit der echte
Verlauf sauber bleibt). Gemessen werden die Erfolgskriterien aus dem README (Kapitel Erfolgskriterien).
Antworten landen in data/eval/ (gitignored, enthalten Kursmaterial).
"""
import json
import statistics
import time
from datetime import datetime

import yaml

from study_agent.config import REPO_DIR, load_settings

FRAGEN = REPO_DIR / "eval" / "testfragen.yaml"


def _bewerten(f: dict, kat: str, state: dict, dauer: float) -> dict:
    r = state.get("response") or {}
    antwort = (r.get("answer") or "").casefold()
    quellen = " ".join(r.get("quellen") or []).casefold()
    tools = state.get("tools_used") or []
    erg = {"gruppe": kat, "frage": f["frage"], "dauer_s": round(dauer, 1),
           "in_scope_ok": state.get("in_scope") == f["in_scope"],
           "kategorie_ok": (not f["in_scope"]) or state.get("category") == f.get("kategorie"),
           "tools_ok": (not f["tools"] and not tools) or bool(set(f["tools"]) & set(tools)),
           "fakten_ok": all(any(w in antwort for w in gruppe) for gruppe in f.get("stichwoerter") or []),
           "quelle_ok": (f.get("quelle") or "").casefold() in quellen if f.get("quelle") else None,
           "quelle_genannt": bool(r.get("quellen")) if f["in_scope"] else None,
           "tools": tools, "kategorie": state.get("category"), "antwort": r.get("answer"), "quellen": r.get("quellen")}
    return erg


def _quote(werte) -> str:
    werte = [w for w in werte if w is not None]
    return f"{sum(werte)}/{len(werte)} ({100 * sum(werte) / len(werte):.0f} %)" if werte else "-"


async def run_eval(args) -> int:
    from study_agent.agent.chat import make_chat_graph
    from study_agent.agent.memory import Context, open_memory

    fragen = yaml.safe_load(FRAGEN.read_text())
    if args.gruppe:
        fragen = {k: v for k, v in fragen.items() if k == args.gruppe}
    s = load_settings()
    ergebnisse = []
    async with open_memory(s.state_dir / "eval.sqlite") as (saver, store):
        graph = await make_chat_graph(checkpointer=saver, store=store)
        lauf = datetime.now().strftime("%Y%m%d-%H%M")
        for kat, liste in fragen.items():
            for i, f in enumerate(liste[:args.limit] if args.limit else liste):
                t0 = time.time()
                try:
                    state = await graph.ainvoke({"messages": [("user", f["frage"])]},
                                                {"configurable": {"thread_id": f"eval-{lauf}-{kat}-{i}"}},
                                                context=Context(user_id="eval"))
                except Exception as exc:
                    state = {"response": {"answer": f"FEHLER {type(exc).__name__}: {exc}"}}
                e = _bewerten(f, kat, state, time.time() - t0)
                ergebnisse.append(e)
                ok = "ok " if e["in_scope_ok"] and e["tools_ok"] and e["fakten_ok"] else "XX "
                print(f"{ok}{kat:<16} {e['dauer_s']:>5}s  {f['frage'][:70]}", flush=True)

    zust = [e for e in ergebnisse if e["gruppe"] != "nicht_zustaendig"]
    print("\nErgebnis")
    print(f"  Zuständigkeit korrekt:      {_quote([e['in_scope_ok'] for e in ergebnisse])}")
    print(f"  Ablehnungen korrekt:        {_quote([e['in_scope_ok'] for e in ergebnisse if e['gruppe'] == 'nicht_zustaendig'])}")
    print(f"  Kategorie korrekt:          {_quote([e['kategorie_ok'] for e in zust])}")
    print(f"  Richtiges Tool:             {_quote([e['tools_ok'] for e in ergebnisse])}")
    print(f"  Fakten korrekt:             {_quote([e['fakten_ok'] for e in zust])}")
    print(f"  Quelle genannt:             {_quote([e['quelle_genannt'] for e in zust])}")
    print(f"  Erwartete Quelle:           {_quote([e['quelle_ok'] for e in zust])}")
    if ergebnisse:
        print(f"  Antwortzeit Median:         {statistics.median(e['dauer_s'] for e in ergebnisse):.1f} s")
    out = s.project_dir / "eval" / f"{datetime.now():%Y-%m-%d-%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1))
    print(f"  Details: {out}")
    return 0
