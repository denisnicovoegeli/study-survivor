"""FastAPI-App des Dashboards: REST-Routen aus study-agent plus Chat (SSE) und Freigaben.

Start: uv run study serve   (http://localhost:8765)
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.errors import GraphRecursionError

from study_agent.config import REPO_DIR

API = "/api/plugins/studium"          # gleicher Pfad wie im Hermes-Plugin, das Frontend bleibt unverändert
STATIC = "/dashboard-plugins/studium/dist"
DIST = REPO_DIR / "web" / "dist"
SCHRITTE = {"summarize": "Verlauf zusammenfassen", "classify": "Frage einordnen", "answer": "Antwort formulieren",
            "tools": "Tools ausführen", "respond": "Antwort mit Quellen", "reject": "Nicht zuständig"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from study_agent.agent.chat import make_chat_graph
    from study_agent.agent.cli_verarbeiten import graph as verarbeiten_graph
    from study_agent.agent.memory import open_memory

    async with open_memory() as (saver, store):
        app.state.chat = await make_chat_graph(checkpointer=saver, store=store)
        app.state.saver = saver
        app.state.verarbeiten = verarbeiten_graph()
        yield


app = FastAPI(title="Study Survivor", lifespan=lifespan)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post(f"{API}/chat")
async def chat(payload: dict = Body(...)):
    """Eine Frage an den Graphen `chat`. Antwort als Server-Sent Events:
    step (Knoten), tool (Tool-Aufruf), token (Text aus `answer`), final (AgentResponse), error."""
    from study_agent.agent.memory import Context

    text = str(payload.get("message") or "").strip()
    if not text:
        raise HTTPException(400, "message fehlt")
    thread = str(payload.get("thread_id") or uuid.uuid4().hex[:12])
    ctx = payload.get("context") or {}
    if ctx.get("file"):
        text += f"\n\n(Geöffnete Datei im Dashboard: {ctx['file']}" + (f", Folie {ctx['folie']}" if ctx.get("folie") else "") + ")"
    graph = app.state.chat
    config = {"configurable": {"thread_id": thread}}

    async def events():
        yield _sse("thread", {"thread_id": thread})
        try:
            async for mode, chunk in graph.astream({"messages": [HumanMessage(text)]}, config,
                                                   context=Context(user_id="stirling"),
                                                   stream_mode=["updates", "messages"]):
                if mode == "messages":
                    msg, meta = chunk
                    if meta.get("langgraph_node") == "answer" and isinstance(msg, AIMessageChunk) and msg.content \
                            and not msg.tool_call_chunks:
                        yield _sse("token", {"text": msg.content if isinstance(msg.content, str) else ""})
                    continue
                for node, upd in chunk.items():
                    yield _sse("step", {"node": node, "label": SCHRITTE.get(node, node)})
                    if node == "answer" and upd:
                        for m in upd.get("messages", []):
                            for tc in getattr(m, "tool_calls", []) or []:
                                yield _sse("tool", {"name": tc["name"], "args": tc["args"]})
            state = (await graph.aget_state(config)).values
            yield _sse("final", {"thread_id": thread, "category": state.get("category"),
                                 "in_scope": state.get("in_scope"), "tools_used": state.get("tools_used") or [],
                                 **(state.get("response") or {})})
        except GraphRecursionError:
            yield _sse("error", {"message": "Der Agent hat zu viele Schritte gebraucht und abgebrochen. "
                                            "Formuliere die Frage enger oder frag in einem neuen Chat."})
        except Exception as exc:  # Fehler als Event, damit das Frontend etwas anzeigen kann
            from study_agent.agent.evaluation import vom_anbieter_blockiert
            if vom_anbieter_blockiert(exc):
                yield _sse("error", {"message": "Der Inhaltsfilter des Modellanbieters hat die Anfrage blockiert, "
                                                "vermutlich wegen verdächtiger Anweisungen in einem gefundenen Dokument. "
                                                "Formuliere die Frage anders oder wähle das Dokument im Modul ab."})
            else:
                yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get(f"{API}/chat/threads")
async def chat_threads():
    """Threads aus dem Checkpointer, neueste zuerst, mit erster Frage als Titel."""
    seen: dict[str, str] = {}
    async for cp in app.state.saver.alist(None):
        tid = cp.config["configurable"]["thread_id"]
        if tid not in seen and cp.checkpoint.get("ts"):
            seen[tid] = cp.checkpoint["ts"]
    out = []
    for tid, ts in sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:30]:
        msgs = (await app.state.chat.aget_state({"configurable": {"thread_id": tid}})).values.get("messages", [])
        first = next((m.content for m in msgs if isinstance(m, HumanMessage)), "")
        out.append({"thread_id": tid, "updated": ts, "title": first.split("\n")[0][:80]})
    return {"threads": out}


@app.get(f"{API}/chat/history")
async def chat_history(thread_id: str = Query(...)):
    values = (await app.state.chat.aget_state({"configurable": {"thread_id": thread_id}})).values
    out = []
    for m in values.get("messages", []):
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "text": m.content.split("\n\n(Geöffnete Datei")[0]})
        elif isinstance(m, AIMessage) and m.content and not m.tool_calls:
            out.append({"role": "assistant", "text": m.content})
    if out and out[-1]["role"] == "assistant" and values.get("response"):
        out[-1]["quellen"] = values["response"].get("quellen", [])
    return {"thread_id": thread_id, "messages": out}


@app.get(f"{API}/graphs")
async def graphs():
    """Diagramme (Mermaid aus dem Code) und Erklärtexte für die Ansicht «LangGraph»."""
    from study_agent.server.graph_info import graph_info
    return graph_info({"chat": app.state.chat, "verarbeiten": app.state.verarbeiten})


@app.get(f"{API}/freigaben")
async def freigaben():
    from study_agent.agent.verarbeiten import open_freigaben
    return {"freigaben": await asyncio.to_thread(open_freigaben, app.state.verarbeiten)}


@app.post(f"{API}/freigaben/{{thread_id}}")
async def freigabe_entscheid(thread_id: str, payload: dict = Body(...)):
    """Entscheid zur Freigabe: Command(resume={decision, feedback}) an den Graphen verarbeiten."""
    from langgraph.types import Command

    decision = payload.get("decision")
    if decision not in ("approve", "edit", "reject"):
        raise HTTPException(400, "decision muss approve, edit oder reject sein")
    g = app.state.verarbeiten
    cfg = {"configurable": {"thread_id": thread_id}}
    if not (await asyncio.to_thread(g.get_state, cfg)).next:
        raise HTTPException(404, "keine offene Freigabe")
    await asyncio.to_thread(g.invoke, Command(resume={"decision": decision, "feedback": payload.get("feedback", "")}), cfg)
    st = await asyncio.to_thread(g.get_state, cfg)
    v = st.values
    return {"thread_id": thread_id, "offen": bool(st.next), "entscheid": v.get("entscheid"),
            "geschrieben": v.get("geschrieben", []), "pruefung": v.get("pruefung")}


@app.post(f"{API}/verarbeiten")
async def verarbeiten_start(payload: dict = Body(...)):
    """Startet den Graphen `verarbeiten` für eine Datei im Hintergrund (Knopf im Explorer und in der Übersicht)."""
    from study_agent.agent.verarbeiten import thread_id

    rel = str(payload.get("rel") or "")
    if not rel:
        raise HTTPException(400, "rel fehlt")
    laeufe = app.state.__dict__.setdefault("laeufe", {})
    if laeufe.get(rel, {}).get("status") == "läuft":
        return {"rel": rel, **laeufe[rel]}
    tid = thread_id(rel)
    laeufe[rel] = {"status": "läuft", "thread_id": tid}

    def run():
        g = app.state.verarbeiten
        cfg = {"configurable": {"thread_id": tid}}
        try:
            g.invoke({"rel": rel, "sabotage": False, "force": bool(payload.get("force"))}, cfg)
            st = g.get_state(cfg)
            laeufe[rel] = {"status": "freigabe" if st.next else "fertig", "thread_id": tid,
                           "geschrieben": st.values.get("geschrieben", [])}
        except Exception as exc:
            laeufe[rel] = {"status": "fehler", "thread_id": tid, "fehler": f"{type(exc).__name__}: {exc}"}

    asyncio.get_running_loop().run_in_executor(None, run)
    return {"rel": rel, **laeufe[rel]}


@app.get(f"{API}/verarbeiten")
async def verarbeiten_status():
    return {"laeufe": app.state.__dict__.get("laeufe", {})}


# übernommene Routen (Dateien, Lesen, PDF, Suche, Karten, Kalender, Modul, Übersicht, Upload)
from study_agent.server.dashboard.plugin_api import make_router  # noqa: E402

app.include_router(make_router(), prefix=API)

if DIST.exists():
    app.mount(STATIC, StaticFiles(directory=DIST), name="static")


@app.get("/")
async def index():
    if not (DIST / "index.html").exists():
        raise HTTPException(503, "Frontend nicht gebaut: cd web && npm install && npm run build")
    # no-cache: nach einem neuen Build lädt der Browser sofort das neue Bundle
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
