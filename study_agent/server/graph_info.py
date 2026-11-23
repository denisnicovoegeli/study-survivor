"""Ansicht «LangGraph» im Dashboard: Diagramme aus dem Code und Erklärtexte.

Die Diagramme kommen aus `graph.get_graph().draw_mermaid()` der laufenden Graphen, stimmen also immer mit dem
Code überein. Die Texte stehen hier als Daten; Codeverweise sind (Datei, Suchtext), die Zeile wird beim Abruf
gesucht, damit sie nach Änderungen nicht veraltet.
"""
from functools import lru_cache

from study_agent.config import REPO_DIR

CHAT = "study_agent/agent/chat.py"
VERARBEITEN = "study_agent/agent/verarbeiten.py"

GRAPHEN = {
    "chat": {
        "titel": "Graph chat",
        "untertitel": "Fragen zum Studium im Dashboard-Chat",
        "beschreibung": (
            "Jede Frage im Chat läuft durch diesen Graphen. Er ordnet die Frage zuerst ein, beantwortet nur "
            "Studienfragen und holt sich dafür Termine und Kursmaterial über Tools. Der Verlauf wird pro "
            "thread_id in SQLite gespeichert, darum versteht der Agent auch Rückfragen."),
        "state": [
            ("messages", "Verlauf als Liste, mit dem Reducer add_messages zusammengeführt"),
            ("summary", "Zusammenfassung der früheren Runden"),
            ("in_scope, category", "Ergebnis von classify"),
            ("tools_used", "Namen der Tools dieser Runde"),
            ("response", "AgentResponse mit Antwort, Quellen und Ergänzungs-Marke"),
        ],
        "code": (CHAT, "def build_chat_graph"),
        "knoten": {
            "summarize": {
                "art": "LLM", "woche": "SW8",
                "text": "Fasst ab der zweiten Frage die vorige Runde in summary zusammen. So bleibt der Kontext "
                        "kurz, auch wenn der Thread lang wird.",
                "liest": ["messages", "summary"], "schreibt": ["summary"],
                "code": (CHAT, "async def summarize"),
            },
            "classify": {
                "art": "LLM, strukturiert", "woche": "SW5",
                "text": "Ordnet die Frage mit with_structured_output(Classification, method=\"json_schema\") ein: "
                        "zuständig ja oder nein und eine von fünf Kategorien. Bitten, eine bewertete Abgabe zu "
                        "schreiben, gelten als nicht zuständig.",
                "liest": ["messages", "summary", "Store: profil"], "schreibt": ["in_scope", "category"],
                "code": (CHAT, "async def classify"),
            },
            "reject": {
                "art": "Code", "woche": "SW5",
                "text": "Fester Text ohne Modellaufruf, wenn die Frage nicht zum Studium gehört. Leitplanke aus "
                        "dem System-Prompt, aber deterministisch umgesetzt.",
                "liest": [], "schreibt": ["messages", "response"],
                "code": (CHAT, "async def reject"),
            },
            "answer": {
                "art": "LLM mit Tools", "woche": "SW5, SW8",
                "text": "System-Prompt (Ziel, Rolle, Instruktionen, Leitplanken) plus Profil aus dem Store und "
                        "Zusammenfassung. Der Verlauf wird mit trim_messages(start_on=\"human\") gekürzt. Das "
                        "Modell entscheidet über bind_tools, ob es ein Tool braucht.",
                "liest": ["messages", "summary", "Store: profil"], "schreibt": ["messages"],
                "code": (CHAT, "async def answer"),
            },
            "tools": {
                "art": "ToolNode", "woche": "SW6, SW7",
                "text": "Führt die Tool-Aufrufe aus: termine (lokal), kursmaterial_suchen (Hybrid-RAG) und die "
                        "drei Tools des eigenen MCP-Servers kursmaterial. Ein Fehler-Wrapper macht Fehler zur "
                        "ToolMessage, RetryPolicy wiederholt bei ConnectionError bis zu dreimal. Danach zurück "
                        "zu answer.",
                "liest": ["messages (Tool-Calls)"], "schreibt": ["messages (ToolMessages)"],
                "code": (CHAT, 'g.add_node("tools"'),
            },
            "respond": {
                "art": "LLM, strukturiert", "woche": "SW5",
                "text": "Formt die Antwort in AgentResponse um: Text, Quellen als Kurs / Datei / Folie und die "
                        "Marke, ob eigene Ergänzungen ausserhalb des Kursmaterials drin sind.",
                "liest": ["messages"], "schreibt": ["response", "tools_used"],
                "code": (CHAT, "async def respond"),
            },
        },
        "kanten": [
            "classify → answer oder reject: bedingte Kante über route() nach in_scope.",
            "answer → tools oder respond: tools_condition prüft, ob die letzte Nachricht Tool-Calls hat.",
            "tools → answer: Schleife, bis das Modell keine Tools mehr braucht.",
        ],
    },
    "verarbeiten": {
        "titel": "Graph verarbeiten",
        "untertitel": "Neue Unterlagen aus Moodle aufbereiten (Multi-Agent)",
        "beschreibung": (
            "Läuft im täglichen Cron und über den Knopf «Verarbeiten». Agent 1 schreibt Folien ab und erstellt "
            "Zusammenfassung, Cheatsheet und Termine. Agent 2, ein Modell eines anderen Anbieters, prüft das "
            "gegen den Rohtext (Vier-Augen-Prinzip). Kommt der Entwurf nach zwei Runden nicht durch, entscheidet "
            "ein Mensch."),
        "state": [
            ("rel, route", "Datei und Art der Verarbeitung (voll oder info)"),
            ("texts, images", "Rohtext pro Seite und Seitenbilder der visuellen Seiten"),
            ("folien, artefakte", "Entwurf von Agent 1"),
            ("pruefung, feedback, runde", "Urteil von Agent 2 und Rundenzähler"),
            ("entscheid, geschrieben", "Ergebnis der Freigabe und geschriebene Dateien"),
        ],
        "code": (VERARBEITEN, "def build_verarbeiten_graph"),
        "knoten": {
            "read": {
                "art": "Code", "woche": "SW8",
                "text": "Holt Rohtext und Seitenbilder einer offenen Datei. Das Original wird nur hier geöffnet, "
                        "einmal pro Datei.",
                "liest": ["rel", "force"], "schreibt": ["route", "texts", "images", "runde"],
                "code": (VERARBEITEN, "def read"),
            },
            "extract": {
                "art": "Agent 1, Vision", "woche": "SW8",
                "text": "Schreibt die Folien wörtlich ab (Rohtext plus Seitenbild) und erstellt Zusammenfassung, "
                        "Cheatsheet, Begriffe und Termine als strukturierte Ausgabe. In der zweiten Runde mit dem "
                        "Feedback des Prüfers.",
                "liest": ["texts", "images", "feedback"], "schreibt": ["folien", "artefakte", "runde"],
                "code": (VERARBEITEN, "def extract"),
            },
            "check": {
                "art": "Agent 2, anderes Modell", "woche": "SW8",
                "text": "Prüft den Entwurf gegen den Rohtext mit festen Kriterien: fehlende Folien, falsche Zahlen, "
                        "erfundene Termine. after_check leitet weiter: ok zu write, sonst zurück zu extract, nach "
                        "MAX_ROUNDS = 2 zur Freigabe.",
                "liest": ["folien", "artefakte", "texts"], "schreibt": ["pruefung", "feedback"],
                "code": (VERARBEITEN, "def check"),
            },
            "freigabe": {
                "art": "Human in the Loop", "woche": "SW8",
                "text": "interrupt() hält den Graphen an und speichert den Stand im Checkpointer. Im Dashboard "
                        "erscheint eine Freigabe-Karte; Command(resume={decision, feedback}) setzt fort: approve "
                        "zu write, edit zurück zu extract, reject beendet.",
                "liest": ["folien", "pruefung"], "schreibt": ["entscheid", "feedback"],
                "code": (VERARBEITEN, "def freigabe"),
            },
            "write": {
                "art": "Code", "woche": "",
                "text": "Schreibt .folien.md, Zusammenfassung, Cheatsheet und Modulangaben und ergänzt neue Termine "
                        "in termine/<Kurs>.yaml. Fester Code nach den Agenten, wie im Rechnungs-Beispiel.",
                "liest": ["folien", "artefakte"], "schreibt": ["geschrieben"],
                "code": (VERARBEITEN, "def write"),
            },
            "done": {
                "art": "Code", "woche": "",
                "text": "Markiert die Datei als verarbeitet (study done).",
                "liest": ["rel"], "schreibt": ["geschrieben"],
                "code": (VERARBEITEN, "def done"),
            },
        },
        "kanten": [
            "check → write, extract oder freigabe: bedingte Kante über after_check.",
            "freigabe → write, extract oder Ende: dynamisch über Command(goto=...), deshalb destinations im "
            "add_node.",
        ],
    },
}

BAUSTEINE = [
    {"woche": "SW5", "baustein": "StateGraph von Hand, State als TypedDict",
     "umsetzung": "Zwei Graphen mit eigenem State, Knoten und bedingten Kanten", "code": (CHAT, "class ChatState")},
    {"woche": "SW5", "baustein": "System-Prompt mit Ziel, Rolle, Instruktionen, Leitplanken",
     "umsetzung": "Regeln aus study-agent: nur Kursmaterial, Ergänzungen markieren, Quellen nennen",
     "code": ("study_agent/agent/prompts.py", "SYSTEM_PROMPT")},
    {"woche": "SW5", "baustein": "Strukturierte Ausgabe",
     "umsetzung": "Classification, AgentResponse, Folien, Artefakte, Pruefung mit method=\"json_schema\"",
     "code": (CHAT, "class Classification")},
    {"woche": "SW5", "baustein": "Lokales Tool und Tracing",
     "umsetzung": "Tool termine; Traces in LangSmith über LANGSMITH_API_KEY",
     "code": ("study_agent/agent/tools.py", "def termine")},
    {"woche": "SW6", "baustein": "ToolNode, Fehler-Wrapper, RetryPolicy",
     "umsetzung": "awrap_tool_call=handle_tool_errors, Retry auf ConnectionError", "code": (CHAT, "async def handle_tool_errors")},
    {"woche": "SW6", "baustein": "Eigener MCP-Server (FastMCP, stdio) und MultiServerMCPClient",
     "umsetzung": "Server kursmaterial mit kurse_auflisten, dateien_auflisten, datei_lesen",
     "code": ("study_agent/agent/mcp_server.py", "FastMCP(")},
    {"woche": "SW7", "baustein": "Embeddings, Vektor-DB, Hybrid Retrieval mit RRF",
     "umsetzung": "Chroma (Apertus-Embeddings) plus SQLite-FTS5 (BM25), zusammengeführt mit RRF k=60",
     "code": ("study_agent/agent/rag.py", "def hybrid_search")},
    {"woche": "SW8", "baustein": "Checkpointer mit thread_id, Store pro Nutzer",
     "umsetzung": "AsyncSqliteSaver und AsyncSqliteStore, Namespace (user_id, \"profil\")",
     "code": ("study_agent/agent/memory.py", "async def open_memory")},
    {"woche": "SW8", "baustein": "trim_messages und Summary-Knoten",
     "umsetzung": "summarize vor classify, trim_messages in answer", "code": (CHAT, "trim_messages(state")},
    {"woche": "SW8", "baustein": "Human in the Loop: interrupt() und Command(resume=...)",
     "umsetzung": "Knoten freigabe, Freigabe-Karte im Dashboard", "code": (VERARBEITEN, "interrupt({")},
    {"woche": "SW8", "baustein": "Multi-Agent mit Vier-Augen-Prinzip",
     "umsetzung": "extract (Vision-Modell) und check (anderer Anbieter), höchstens zwei Runden",
     "code": (VERARBEITEN, "def after_check")},
]

WEGGELASSEN = [
    ("Tavily-Websuche", "Antworten sollen nur aus dem Kursmaterial kommen."),
    ("Time Travel", "Für Studienfragen gibt es keinen Grund, alte Zustände zu verzweigen."),
    ("Decision Models, DeltaChannel", "Für diesen Use Case nicht nötig."),
]


@lru_cache(maxsize=None)
def _zeile(datei: str, suche: str) -> int | None:
    try:
        for i, line in enumerate((REPO_DIR / datei).read_text(encoding="utf-8").splitlines(), 1):
            if suche in line:
                return i
    except OSError:
        pass
    return None


def _ref(code) -> dict:
    datei, suche = code
    return {"datei": datei, "zeile": _zeile(datei, suche)}


def _mermaid(compiled) -> str:
    """Mermaid aus LangGraph, ohne dessen Farben (das Dashboard setzt eigene) und mit deutschen Start/Ende."""
    lines = [ln for ln in compiled.get_graph().draw_mermaid().splitlines() if not ln.strip().startswith("classDef")]
    text = "\n".join(lines)
    return (text.replace("([<p>__start__</p>]):::first", "([Start]):::first")
            .replace("([<p>__end__</p>]):::last", "([Ende]):::last")
            .replace("&nbsp;__end__&nbsp;", "&nbsp;fertig&nbsp;")
            .replace("__tools = ", ""))


def graph_info(graphs: dict) -> dict:
    """graphs: Name → kompilierter Graph. Liefert Diagramm und Erklärung je Graph plus Kursbausteine."""
    out = []
    for name, compiled in graphs.items():
        info = GRAPHEN[name]
        out.append({
            "id": name,
            "titel": info["titel"],
            "untertitel": info["untertitel"],
            "beschreibung": info["beschreibung"],
            "mermaid": _mermaid(compiled),
            "state": [{"feld": f, "text": t} for f, t in info["state"]],
            "kanten": info["kanten"],
            "code": _ref(info["code"]),
            "knoten": {k: {**{x: y for x, y in v.items() if x != "code"}, "code": _ref(v["code"])}
                       for k, v in info["knoten"].items()},
        })
    return {
        "graphen": out,
        "bausteine": [{**{x: y for x, y in b.items() if x != "code"}, "code": _ref(b["code"])} for b in BAUSTEINE],
        "weggelassen": [{"was": w, "warum": g} for w, g in WEGGELASSEN],
    }
