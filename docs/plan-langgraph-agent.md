# Plan: Study Agent als LangGraph-Projekt (GenAI & Agentensysteme)

Stand 2026-11-09. Branch `stirling` im Repo study-survivor. Abgabe: Präsentation am 23.11.2026, 13.00 Uhr (10 Min.).

## Ziel

Der Study Agent aus `~/Apps/study-agent` wird als LangGraph-Agent neu gebaut, ohne Hermes. Alles läuft lokal auf dem Mac: moodle-dl lädt nach `~/Apps/moodle-dl`, Dashboard und Agent laufen auf `localhost`, der Cron über launchd. Die Modelle laufen extern über den LiteLLM der FHNW. Die Pipeline (moodle-dl, convert, extract), ein vereinfachtes Dashboard und ein täglicher Cron kommen mit. Der Agent nutzt nur Bausteine aus SW4 bis SW8; SW9 (Interface, Evaluation, Safeguarding) folgt am 16.11.

## Quellen

- Folien SW4 bis SW8 (`*.folien.md` und Rohtext), Semesterprogramm, Demo-Notebooks SW4 bis SW8 (SWISS-Agent, `05_custom_mcp_server.py`, `08b_multi_agent_rechnungen.ipynb`).
- Bestehender Code in `~/Apps/study-agent` (Pipeline, Dashboard, Regeln aus `CLAUDE.md`).

## Kursbausteine und wo sie im Agenten landen

| Woche | Baustein (laut Folien) | Umsetzung |
|---|---|---|
| SW4 | Use Case, User Stories, Erfolgskriterien, Modellwahl, LiteLLM | README-Kapitel; Hauptmodell `gpt-5.6-luna` über den LiteLLM der FHNW, zweites Modell eines anderen Anbieters für die Prüfung (SW8) |
| SW5 | StateGraph von Hand, State mit Rohdaten, System-Prompt (Ziel, Rolle, Instruktionen, Leitplanken), strukturierte Ausgabe, lokales Tool, Tracing | Graph `classify → answer ⇄ tools → respond`, `with_structured_output(..., method="json_schema")`, Tool `termine`, LangSmith über `LANGSMITH_API_KEY` |
| SW6 | gute Tool-Beschreibungen, `ToolNode`, eigener MCP-Server (FastMCP, stdio), `MultiServerMCPClient`, Fehler-Wrapper, `RetryPolicy` | MCP-Server `kursmaterial` (Kurse, Dateien, Datei lesen), `awrap_tool_call=handle_tool_errors`, Retry auf `ConnectionError` |
| SW7 | Loader, Chunking, Embeddings, Vektor-DB, Hybrid Retrieval mit RRF (k=60) | Tool `kursmaterial_suchen`: Chroma (dense, Embeddings `apertus-v1.1-swiss-embed-0.4b` über LiteLLM) plus die bestehende SQLite-FTS5-Suche (sparse, BM25) aus `suche.py`, zusammengeführt mit RRF |
| SW8 Memory | Checkpointer mit `thread_id`, produktiv SQLite, `trim_messages`, Summary-Knoten, Store mit Namespace pro Nutzer | `SqliteSaver` (Paket `langgraph-checkpoint-sqlite`), Knoten `summarize` vor `classify`, `trim_messages(..., start_on="human")` in `answer`, Store `(user_id, "profil")` für aktuelle Kurse und Sprache |
| SW8 HITL | `interrupt()` und `Command(resume=...)`, Entscheide approve/edit/reject/respond | Freigabe vor jedem Schreiben in `lernen/` und bei einer Verarbeitung, die nach `MAX_ROUNDS` nicht durch die Prüfung kommt |
| SW8 Multi-Agent | Vier-Augen-Prinzip wie im Rechnungs-Beispiel: Agent liest aus, zweites Modell prüft gegen eine zweite Quelle, Schleife mit Rundengrenze, danach fester Code | Graph `verarbeiten`: `read → extract (Vision) → check (anderes Modell, gegen den Rohtext) → write → done` |
| SW9 (später) | Interface, Evaluation, Safeguarding | Dashboard-Chat als Interface, Testfragen und Evaluation, Leitplanken im Prompt; nach der Vorlesung am 16.11. planen |

Bewusst weggelassen, weil für den Use Case nicht nötig: Tavily-Websuche, Decision Models, Time Travel, DeltaChannel.

## Architektur

```
moodle-dl (Cron, täglich)
  → study convert   (Rohtext pro Seite, Klasse, Marke „visuell“; übernommen)
  → Graph verarbeiten (Multi-Agent, ersetzt Subagent folien-extraktor und study extract)
  → Index neu bauen (Chroma + FTS5)
  → Briefing (Datei, optional Telegram)

Dashboard (React, vereinfacht) ──REST──► FastAPI
                                └─SSE───► Graph chat (Checkpointer SQLite, Store)
                                               ├─ Tool termine         (lokal)
                                               ├─ Tool kursmaterial_suchen (Hybrid-RAG)
                                               └─ MCP kursmaterial     (stdio)
```

### Graph `chat` (Fragen zum Studium)

- **State**: `messages`, `summary`, `in_scope`, `category`, `tools_used`, `response`.
- **summarize**: fasst die vorige Runde zusammen (wie SW8, ab der zweiten Frage).
- **classify**: strukturierte Ausgabe `Classification(reason, in_scope, category)`, Kategorien `termine | inhalt | pruefung | organisation | sonstiges`. Bitten, eine bewertete Abgabe zu schreiben, gelten als nicht zuständig.
- **reject**: fester Text, kein Modellaufruf.
- **answer**: System-Prompt plus Zusammenfassung plus Profil aus dem Store, Verlauf mit `trim_messages` gekürzt, `bind_tools`.
- **tools**: `ToolNode` mit Fehler-Wrapper, `RetryPolicy(max_attempts=3, retry_on=ConnectionError)`, Rückkante zu `answer`.
- **respond**: `AgentResponse(answer, quellen: list[str], ergaenzung: bool)`. Quellen als Kurs, Datei, Folie.

System-Prompt aus den Regeln von study-agent: Inhalte nur aus dem Kursmaterial, eigene Ergänzungen als „(Ergänzung, nicht aus Kursmaterial)“ markieren, Quelle nennen, Termine immer über das Tool, keine bewerteten Abgaben schreiben, Schweizer Rechtschreibung.

### Graph `verarbeiten` (Multi-Agent, SW8)

1. **read** (Code): Rohtext und Seitenbilder der visuellen Seiten einer Datei aus `study pending` holen. PDFs öffnet nur dieser Graph, einmal pro Datei (Regel aus study-agent).
2. **extract** (Agent 1, Vision-Modell): erstellt `*.folien.md`, Zusammenfassung, Cheatsheet und das Info-JSON (Begriffe, Termine, Projekt, Prüfung) als strukturierte Ausgabe. Bei Wiederholung mit `feedback`.
3. **check** (Agent 2, anderes Modell): prüft gegen den Rohtext mit klaren Kriterien (fehlende Folien, falsche Zahlen, erfundene Termine). Bei Ablehnung zurück zu `extract`, höchstens `MAX_ROUNDS = 2`.
4. **freigabe** (HITL): nur wenn `check` nach `MAX_ROUNDS` noch ablehnt: `interrupt()` mit Entwurf und Beanstandung; Entscheid im Dashboard oder in der CLI (approve, edit, reject).
5. **write** und **done** (Code): Dateien schreiben, Termine in `termine/<Kurs>.yaml` ergänzen, `study done`.

### Was aus study-agent übernommen wird

| Teil | Quelle | Anpassung |
|---|---|---|
| LiteLLM-Zugang | `src/study_agent/llm.py`, `config.py` | Key weiter aus `~/.config/aisl.env` oder `.env`; Hermes-Pfade entfernen |
| Pipeline | `moodle_db.py`, `moodle_api.py`, `convert.py`, `classify.py`, `pdf_pages.py`, `pipeline.py`, `termine.py`, `eigene.py`, `modul.py`, `suche.py`, `briefing.py`, `cli.py` | `extract.py` und `regenerate.py` werden durch den Graphen `verarbeiten` ersetzt; `projekte.py` fällt weg |
| Tests | `tests/` der übernommenen Module | nur die, die ohne Hermes laufen |
| Dashboard-Backend | `hermes/dashboard/studium/dashboard/*.py` | als FastAPI-App statt Hermes-Plugin; `routes_auftraege.py`, Kanban- und Projekt-Funktionen in `plugin_api.py` fallen weg |
| Dashboard-Frontend | `hermes/dashboard/studium/web/` | ohne die Ansichten Projekte (`Projects.jsx`) und Kanban (`Kanban.jsx`); `SDK.authedFetch` durch `fetch` ersetzen; `gateway.js` (Hermes-WebSocket) durch einen SSE-Client ersetzen |
| Cron | `scripts/daily.sh`, `launchd/ch.fhnw.study-agent.plist` | Pfade auf study-survivor; nach `convert` den Graphen `verarbeiten` und den Index-Aufbau aufrufen |
| Daten | `knowledge/`, `lernen/`, `termine/`, `klassen.yaml`, `projekte/`, `state/` | Kopie nach `data/` für alle Kurse des aktuellen Semesters; `data/` ist gitignored (Kursmaterial und Namen gehören nicht ins Repo) |

Dashboard danach: Dateien, Lesen und PDF, Suche, Karten, Kalender, Modul, Übersicht, Chat, Upload. Ohne Projekte und Kanban, damit auch ohne Auftragsbrett-Cron.

Nicht übernommen: Hermes (Plugin-SDK, Skills, Goals, Monitor-Cron), Auftragsbrett, Pi-Compose. Der Pi-Betrieb kann nach der Präsentation folgen.

### Regeln, die mitkommen

- `moodle-dl/config.json` enthält den Moodle-Token: nie lesen, ausgeben oder committen. Gilt auch für `content_fileurl` aus der DB.
- Moodle nur lesend.
- `.env` mit `LITELLM_API_KEY` und `LANGSMITH_API_KEY` ist gitignored, im Repo nur `.env.example`.

## Ordnerstruktur

```
study-survivor/            (Branch stirling)
  study_agent/
    llm.py  config.py  cli.py
    pipeline/              moodle_db, convert, classify, pdf_pages, termine, eigene, modul, suche, briefing
    agent/
      prompts.py           System-, Klassifikations-, Summary-, Prüf-Prompt
      tools.py             termine
      rag.py               Chunking, Chroma, Hybrid mit RRF, Index-Aufbau
      mcp_server.py        FastMCP „kursmaterial“
      chat.py              Graph chat
      verarbeiten.py       Graph verarbeiten
      memory.py            SqliteSaver und Store
    server/                FastAPI: REST-Routen und SSE für den Chat
  web/                     React-Dashboard (Vite)
  scripts/daily.sh         Cron
  data/                    gitignored
  tests/
  pyproject.toml  .env.example  README.md
```

Die Branches `denis-the-menace` und `silian` haben je ein eigenes `main.py`. Nichts davon wird überschrieben; ein gemeinsamer Stand wird später über Pull Requests nach `main` abgestimmt.

## Schritte (jeder endet mit einem lauffähigen Stand)

1. **Gerüst und Daten**: uv-Projekt in study-survivor, Pakete mit geprüften Versionen (langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-mcp-adapters 0.3.2, mcp 1.30.0, langchain-chroma), Pipeline-Module und Tests übernehmen, Daten nach `data/` kopieren. Nachweis: `uv run study deadlines`, `study termine` und `pytest` laufen.
2. **Chat-Graph SW5 bis SW7**: classify, reject, answer, tools, respond; Tool `termine`, MCP-Server, Hybrid-RAG, Tracing. Nachweis: drei Testfragen in der CLI (Termin, Inhalt, nicht zuständig) mit Trace in LangSmith.
3. **Memory SW8**: SqliteSaver, summarize, trimming, Store. Nachweis: Rückfrage im selben Thread wird verstanden, nach einem Neustart ist der Verlauf noch da, ein anderer Thread kennt ihn nicht.
4. **Graph verarbeiten mit HITL**: extract, check, freigabe, write, done. Nachweis: eine offene Datei aus `study pending` läuft durch, eine absichtlich fehlerhafte Extraktion landet in der Freigabe.
5. **Dashboard**: FastAPI mit den übernommenen Routen, Frontend ohne Projekte und Kanban, Chat über SSE, Freigabe-Karte für `interrupt()`. Nachweis: Screenshot mit Chat-Antwort und Quellen.
6. **Cron**: `daily.sh` mit moodle-dl, convert, verarbeiten (nur ohne Freigabefall automatisch), Index, Briefing; launchd auf dem Mac. Nachweis: Lauf von Hand, Log ohne Fehler.
7. **SW9-Vorbereitung**: Testfragen (5 pro Kategorie) und Erfolgskriterien aus SW4 messbar machen, Grundlage für Evaluation und Safeguarding am 16.11.

## Offene Punkte

- Mac-Stand von moodle-dl hinkt hinterher: SW8 liegt bisher nur auf dem Pi. Vor Schritt 1 läuft `moodle-dl -p ~/Apps/moodle-dl` einmal auf dem Mac, und der launchd-Job `ch.fhnw.study-agent` von study-agent wird abgelöst, damit nicht zwei Crons parallel laden.

- Zweites Modell für `check`: welches Modell eines anderen Anbieters auf dem Proxy verfügbar ist (`/v1/models` abfragen).
- Telegram für das Briefing: übernehmen oder nur Datei und Dashboard.
- `~/Apps/genai-study-agent` (heute angelegt, nur uv-Projekt und Datenkopie) wird nach Schritt 1 gelöscht.
