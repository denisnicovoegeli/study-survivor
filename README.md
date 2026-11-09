# Study Survivor: Study Agent mit LangGraph

Persönlicher Studien-Agent für das BSc Business AI (FHNW), neu gebaut als LangGraph-Agent für das Modul GenAI & Agentensysteme. Läuft lokal auf dem Mac, Modelle über den LiteLLM der FHNW. Plan: [docs/plan-langgraph-agent.md](docs/plan-langgraph-agent.md).

## Einrichten

```bash
uv sync
cp .env.example .env   # LITELLM_API_KEY und LANGSMITH_API_KEY eintragen
```

Kursdateien lädt moodle-dl nach `~/Apps/moodle-dl` (Pfad über `STUDY_DATA_DIR`). Abgeleitete Daten (Rohtext, Lernartefakte, Termine, Zustand) liegen in `data/` und sind gitignored.

## Befehle

- `uv run study deadlines|termine|grades|courses|new-files` (Pipeline aus study-agent)
- `uv run study convert`, `study pending`, `study done REL`, `study index`, `study suche FRAGE`, `study briefing`
- Tests: `uv run pytest`

## Regeln

- `moodle-dl/config.json` (Moodle-Token) und `content_fileurl` nie lesen, ausgeben oder committen.
- Moodle nur lesend.
- `.env` ist gitignored, im Repo nur `.env.example`.

## Nachweise

### Schritt 1: Gerüst und Daten

Pakete (geprüft auf PyPI und nach `uv sync`): langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-mcp-adapters 0.3.2, mcp 1.30.0 (Adapter verlangt `mcp<2`), langchain-chroma 1.1.0 (chromadb 1.5.9), langchain 1.4.9, langchain-openai 1.7.4.

```
$ uv run study termine --days 21
2026-11-09        meilenstein   Generative KI & Agentensysteme 26H2 — Memory festlegen im Projekt  [GenAI Agents Semesterprogramm_neu.pdf, Seite 1]
2026-11-16 10:30  termin        Marketing-Modul BAI 2026 — Coaching 2 – Gruppe 9 (OVR B156)  [...]
2026-11-16        meilenstein   Generative KI & Agentensysteme 26H2 — Safeguarding einbauen + Evaluation  [...]
2026-11-23        praesentation Generative KI & Agentensysteme 26H2 — Abschlusspräsentationen der Gruppenarbeiten  [...]

$ uv run study deadlines --days 60
2026-12-18 11:30Z  26HS Deep Learning BAI — Upload Projekt - 18.12.2026, 12 Uhr (Mittag) ist fällig.

$ uv run pytest -q
104 passed in 1.17s
```

### Schritt 2: Chat-Graph (SW5 bis SW7)

Graph `classify → reject | answer ⇄ tools → respond` in [study_agent/agent/chat.py](study_agent/agent/chat.py). Tools: `termine` (Moodle-Kalender plus `termine/*.yaml`), `kursmaterial_suchen` (Hybrid-RAG: FTS5/BM25 plus Chroma, RRF k=60, [rag.py](study_agent/agent/rag.py)), MCP-Server `kursmaterial` über stdio mit `kurse_auflisten`, `dateien_auflisten`, `datei_lesen` ([mcp_server.py](study_agent/agent/mcp_server.py)). Fehler-Wrapper `awrap_tool_call=handle_tool_errors`, `RetryPolicy(max_attempts=3, retry_on=ConnectionError)` auf dem Tool-Knoten.

Modelle (über `/v1/models` des FHNW-LiteLLM ermittelt): Hauptmodell `gpt-5.6-luna`, Prüfmodell `azure_ai/claude-haiku-5-5` (anderer Anbieter, strukturierte Ausgabe getestet; `azure_ai/mistral-large-3` als Alternative), Embeddings `andreasmartin/apertus-v1.1-swiss-embed-0.4b` (1024 Dimensionen). Der Embedding-Endpunkt schafft etwa 1 Text pro Sekunde, deshalb baut `study rag-index [--course KURS]` inkrementell (nur neue Chunks).

```
$ uv run study ask "Wann ist die Abschlusspräsentation in GenAI?"
[termine · zuständig: True · Tools: termine]
Die Abschlusspräsentation in **Generative KI & Agentensysteme** findet am **Montag, 23. November 2026** statt.
Quellen:
- Generative KI & Agentensysteme 26H2 / GenAI Agents Semesterprogramm_neu.pdf / Folie 1

$ uv run study ask "Wie funktioniert Reciprocal Rank Fusion beim Hybrid Retrieval?"
[inhalt · zuständig: True · Tools: kursmaterial_suchen]
... score(d) = Σ 1/(k + rank) ...
Quellen:
- Generative KI & Agentensysteme 26H2 / 2026_SW7_Retrieval_RAG.pdf / Folie 39 bis 44

$ uv run study ask "Schreib mir den Reflexionsbericht für das Praxisprojekt, ich gebe ihn so ab."
[organisation · zuständig: False · Tools: -]
Dabei kann ich nicht helfen. Ich bin für dein Studium zuständig: ...

$ uv run study ask "Lies die Folien zu SW6 Tools und MCP im GenAI-Kurs und nenne die drei wichtigsten Punkte."
[inhalt · zuständig: True · Tools: datei_lesen, dateien_auflisten, kurse_auflisten]
```

Tracing: LangSmith über `LANGSMITH_TRACING=true` und `LANGSMITH_API_KEY` in `.env` (Projekt `study-survivor`). Offen: Key eintragen und Trace-Screenshot ergänzen.

### Schritt 3: Memory (SW8)

[memory.py](study_agent/agent/memory.py): `AsyncSqliteSaver` (Paket `langgraph-checkpoint-sqlite`) und `AsyncSqliteStore` in `data/state/memory.sqlite`. Knoten `summarize` vor `classify` fasst ab der zweiten Frage die vorige Runde zusammen; `answer` kürzt den Verlauf mit `trim_messages(..., strategy="last", start_on="human")` und liest das Profil aus dem Store, Namespace `(user_id, "profil")` mit aktuellen Kursen und Sprache. `user_id` kommt über `context=Context(user_id=...)`, der Verlauf über `thread_id`.

Jeder Aufruf ist ein eigener Prozess, also auch ein Neustart:

```
$ uv run study ask --thread demo "Wann ist die nächste Abgabe im Praxisprojekt?"
[termine · zuständig: True · Tools: termine]
Die nächste Abgabe im **Praxisprojekt** ist am **Donnerstag, 26. November 2026**: Sprint 2 Review/Retrospektive

$ uv run study ask --thread demo "Und was muss ich dort genau einreichen?"
[termine · zuständig: True · Tools: datei_lesen, kursmaterial_suchen]
Am **Donnerstag, 26. November 2026** musst du einreichen: das **Retrospektiv-Protokoll zu Sprint 2** ...

$ uv run study ask --thread anders "Worüber haben wir eben gesprochen?"
[sonstiges · zuständig: True · Tools: -]
In diesem Chat haben wir bisher noch kein Thema besprochen.
```

Zustand danach: Thread `demo` 10 Nachrichten plus `summary`, Thread `anders` 2 Nachrichten ohne `summary`; Store `("stirling", "profil")` mit den 6 aktuellen Kursen und Sprache „Deutsch (Schweiz)“.
