# Study Survivor: Study Agent mit LangGraph

Persönlicher Studien-Agent für das BSc Business AI (FHNW), neu gebaut als LangGraph-Agent für das Modul GenAI & Agentensysteme. Läuft lokal auf dem Mac, Modelle über den LiteLLM der FHNW.

## Use Case (SW4)

**Problem:** Im BSc Business AI verteilen sich Termine, Folien und Prüfungsinfos über sechs Moodle-Kurse, viele Termine stehen nur in PDFs (Semesterprogramme, Folien) und nicht im Moodle-Kalender. Suchen kostet Zeit, und Termine gehen verloren.

**Lösung:** Ein Agent, der das Kursmaterial täglich lädt, es von zwei Modellen geprüft aufbereitet (Vier-Augen-Prinzip) und Fragen zu Terminen, Inhalten und Prüfungen mit Quellenangabe beantwortet. Er schreibt keine bewerteten Abgaben.

**User Stories**
- Als Student möchte ich fragen „was steht diese Woche an?“, damit ich keine Abgabe verpasse, auch wenn sie nur in einem PDF steht.
- Als Student möchte ich Fragen zum Stoff mit Folienangabe beantwortet bekommen, damit ich die Stelle im Original nachlesen kann.
- Als Student möchte ich, dass neue Unterlagen automatisch aufbereitet werden (Folientext, Zusammenfassung, Cheatsheet, Termine), damit ich nicht jede Datei selbst öffnen muss.
- Als Student möchte ich bei zweifelhaften Extraktionen selbst entscheiden (freigeben, korrigieren, verwerfen), damit keine erfundenen Termine in meinem Kalender landen.
- Als Student möchte ich, dass der Agent Rückfragen im selben Gespräch versteht und sich meine Kurse merkt.

**Erfolgskriterien (messbar, Grundlage für die Evaluation in SW9)**

| # | Kriterium | Messung | Ziel |
|---|---|---|---|
| E1 | Zuständigkeit korrekt erkannt | `study eval`, 25 Testfragen in [eval/testfragen.yaml](eval/testfragen.yaml) | ≥ 24/25, Ablehnungen 5/5 |
| E2 | Keine bewerteten Abgaben | Testfragen „schreib meinen Bericht“, „löse die Probeprüfung“ | 2/2 abgelehnt |
| E3 | Termine immer über das Tool | Termin-Fragen mit Tool `termine` | 5/5 |
| E4 | Fakten korrekt | erwartete Stichwörter in der Antwort (zuständige Fragen) | ≥ 80 % |
| E5 | Quelle genannt | `quellen` nicht leer bei zuständigen Fragen | ≥ 90 % |
| E6 | Keine erfundenen Termine aus der Verarbeitung | Sabotage-Test `study verarbeiten --fehler` landet in der Freigabe | 100 % erkannt, 0 erfundene Termine in `termine/*.yaml` |
| E7 | Vollständige Folien | `study check-folien` nach `verarbeiten` | 0 fehlende Folien |
| E8 | Antwortzeit | Median über alle Testfragen | ≤ 30 s |
| E9 | Vergleich mit heute | Zeit bis zur Antwort auf „was steht diese Woche an?“ | < 1 Min. statt etwa 5 Min. Suchen in sechs Moodle-Kursen |

**Modellwahl (über `/v1/models` des FHNW-LiteLLM):** `gpt-5.6-luna` für Chat und Extraktion (Tool-Calling, strukturierte Ausgabe, Vision), `azure_ai/claude-haiku-5-5` als Prüfer eines anderen Anbieters (unabhängige zweite Meinung), `andreasmartin/apertus-v1.1-swiss-embed-0.4b` für Embeddings (Schweizer Modell, Deutsch). Alternative Prüfer: `azure_ai/mistral-large-3`.

## Architektur

```
moodle-dl (launchd, Zeitplan im Dashboard)
  → study convert        Rohtext pro Seite
  → study verarbeiten    Graph verarbeiten: read → extract → check ⇄ extract → (freigabe) → write → done
  → study index / rag-index   FTS5 + Chroma
  → study briefing       data/briefings/JJJJ-MM-TT.md

Dashboard (React, web/) ──REST/SSE──► FastAPI (study serve)
                                        └─► Graph chat: summarize → classify → answer ⇄ tools → respond
                                              Tools: termine, kursmaterial_suchen, MCP kursmaterial (stdio)
                                              Memory: AsyncSqliteSaver (thread_id) + Store (user_id, "profil")
```

## Einrichten

```bash
uv sync
cp .env.example .env   # LITELLM_API_KEY und LANGSMITH_API_KEY eintragen
```

Kursdateien lädt moodle-dl nach `~/Apps/moodle-dl` (Pfad über `STUDY_DATA_DIR`). Abgeleitete Daten (Rohtext, Lernartefakte, Termine, Zustand) liegen in `data/` und sind gitignored.

## Befehle

- `uv run study deadlines|termine|grades|courses|new-files` (Pipeline aus study-agent)
- `uv run study convert`, `study pending`, `study done REL`, `study index`, `study suche FRAGE`, `study briefing`
- `uv run study einstellungen [--get SCHLÜSSEL]`, `study zeitplan [status|ein|aus|anwenden]` (Agent-Einstellungen, täglicher Lauf)
- Tests: `uv run pytest`

Im Dashboard: **Module** zeigt alle Moodle-Kurse und eigene Module (Ordner `_eigene/<Name>/` im moodle-dl-Ordner, für Fächer ohne Moodle); hochgeladene Dateien verarbeitet der Agent wie Moodle-Material. **Studium** sammelt modulübergreifende Dokumente in `data/studium/` und übernimmt Prüfungen aus dem Prüfungsplan der Hochschule (.xlsx) als `art: pruefung` in `termine/<Kurs>.yaml`.

**Lernen → Lernplan** verteilt die Themen (Abschnitte) jedes Moduls mit Prüfung im Kalender auf die Wochen bis zur Prüfung; die Woche vor der Prüfung ist Wiederholung. Abgehakte Themen (`data/state/lernplan.json`) fallen weg, der Rest verteilt sich neu. **Semesterwechsel** (unter Module) archiviert alte Module (`semester.archiv` in den Einstellungen): Sie bleiben lesbar, der Agent verarbeitet sie nicht mehr. **Benachrichtigungen** (Agent → Einstellungen) meldet nach dem Briefing neues Material, nahe Fristen und offene Freigaben auf dem Mac und, wenn ein Thema gesetzt ist, per [ntfy](https://ntfy.sh) aufs Handy. **Texterkennung:** `study convert --ocr N` lässt bis zu N eingescannte PDFs ohne Text vom Vision-Modell abschreiben (`verarbeitung.ocr_pro_lauf`, Standard 1 pro Lauf).

**Quellen des Agenten** (im Modul) listet jede Datei aus Moodle und jeden eigenen Upload nach Moodle-Abschnitt: grün, wenn sie im Suchindex steht und der Chat-Agent sie findet; dazu, ob sie zusammengefasst ist, und bei nicht genutzten Einträgen den Grund (Link, Archiv, nicht heruntergeladen, ohne Text). Daten: `GET /quellen?kurs=…` (`study_agent/pipeline/quellen.py`). **Moodle aktualisieren** (unter Module und im Modul) startet im Hintergrund moodle-dl, `convert --current`, `index` und `rag-index` (`POST /moodle/aktualisieren`, Status per GET). Ohne Zusammenfassung durch das Modell, die macht weiter der tägliche Lauf oder der Knopf „verarbeiten“. Die Ausgabe landet nur in `logs/moodle-aktualisieren.log`; läuft gerade `daily.sh`, startet der Knopf nicht.

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

### Schritt 4: Graph `verarbeiten` mit HITL (SW8 Multi-Agent)

[verarbeiten.py](study_agent/agent/verarbeiten.py): `read → extract → check → write → done`, bei Ablehnung zurück zu `extract` (mit Feedback, nur beanstandete Folien neu), nach `MAX_ROUNDS = 2` in `freigabe` mit `interrupt()`. Agent 1 `gpt-5.6-luna` (Vision, strukturierte Ausgabe), Agent 2 `azure_ai/claude-haiku-5-5` prüft gegen den Rohtext; fehlende Folien prüft zusätzlich der Code. Checkpointer `data/state/verarbeiten.sqlite`, ein Thread pro Datei. Ersetzt `study extract`, `regenerate.py` und den Subagenten `folien-extraktor`.

```
$ uv run study verarbeiten "MAKEathon 2026 – .../Information Session MAKEathon module.pdf" --auto
  [   0.4s] read
  [  36.2s] extract
  [  45.9s] check ok=False Beanstandungen=2
  [  80.8s] extract
  [  88.4s] check ok=True Beanstandungen=0
  [  88.4s] write
  [  88.4s] done
  Runden: 2 · Prüfung ok: True · Folien: 10/10
  geschrieben: data/knowledge/.../Information Session MAKEathon module.pdf.folien.md
  geschrieben: data/lernen/.../Information Session MAKEathon module.zusammenfassung.md
  geschrieben: data/lernen/.../Information Session MAKEathon module.cheatsheet.md
  geschrieben: termine: 14 neu

$ uv run study verarbeiten "Cybersecurity BAI/1_Introduction & Foundations/Course Info.pdf" --auto --fehler
  [   0.6s] read
  [  35.9s] extract
  [  44.8s] check ok=False Beanstandungen=2
  [  67.5s] extract
  [  75.9s] check ok=False Beanstandungen=2
  [  75.9s] __interrupt__
  FREIGABE nötig (Thread verarbeiten-eba62806aa36) nach 2 Runden:
    - [fehlt] Folie 8: Seite 8 des Rohtexts (Relevance of Digital Trust, ...) hat im Entwurf keine Folie.
    - [termin] Folie None: Der Termin 'Pflichtabgabe Weihnachtsbericht' am 2026-12-24 um 18:00 ... steht im Rohtext nicht.

$ uv run study freigabe
verarbeiten-eba62806aa36  Cybersecurity BAI/1_Introduction & Foundations/Course Info.pdf  (2 Beanstandungen)
```

`--fehler` ist ein Demo-Schalter: `extract` lässt in jeder Runde eine Folie weg und hängt einen erfundenen Termin an. Entscheid über `study freigabe THREAD --decision approve|edit|reject [--feedback TEXT]` oder die Freigabe-Karte im Dashboard (`Command(resume=...)`). `reject` lässt die Datei offen, `edit` startet eine weitere Runde mit dem Feedback.

Datenstand: Die study-agent-Kopie auf dem Mac war veraltet (nur Deep Learning verarbeitet). `data/` stammt deshalb vom Pi (`/opt/appdata/hermes-study/workspace/study-agent`: knowledge, lernen, termine, klassen.yaml, verarbeitet.json; 39 `.folien.md`, 106 Lerndateien in allen 6 Kursen). Weil die Signatur in `verarbeitet.json` mtime und Grösse der Moodle-Datei enthält und die mtimes auf Mac und Pi verschieden sind, wurde der Pi-Stand bei gleicher Grösse auf die Mac-Signatur umgeschrieben (48 Dateien). `study verarbeiten --force REL` verarbeitet eine schon fertige Datei neu (so entstanden die fehlenden `modul.md` für Marketing und Praxisprojekt). Im Dashboard startet der Knopf „verarbeiten“ (Explorer, Übersicht) den Graphen über `POST /verarbeiten`.

### Schritt 5: Dashboard

```bash
cd web && npm install && npm run build && cd ..
uv run study serve      # http://localhost:8765
```

FastAPI-App [study_agent/server/app.py](study_agent/server/app.py) mit den übernommenen Routen aus dem Hermes-Plugin (Dateien, Lesen und PDF, Suche, Karten, Kalender, Modul, Übersicht, Upload; ohne Projekte, Kanban und Auftragsbrett) unter demselben Pfad `/api/plugins/studium/`. Neu: `POST /chat` (Server-Sent Events: `step`, `tool`, `token`, `final`), `GET /chat/threads`, `GET /chat/history`, `GET /freigaben`, `POST /freigaben/{thread_id}` (`Command(resume={decision, feedback})`). Frontend [web/](web/) als eigenständige Vite-App mit React 19; `SDK.authedFetch` durch `fetch` ersetzt, der Hermes-Gateway durch einen SSE-Client ([sse.js](web/src/chat/sse.js), [ChatPanel.jsx](web/src/chat/ChatPanel.jsx)).

Freigabe-Karte für den `interrupt()` aus Schritt 4. Entscheid „Bearbeiten“ mit Feedback „Folie 8 ergänzen und den Weihnachtstermin entfernen“ startete eine weitere Runde ohne Sabotage; danach Prüfung ok, 15/15 Folien, kein erfundener Termin geschrieben.

### Schritt 6: Cron

[scripts/daily.sh](scripts/daily.sh): moodle-dl → `study convert --current --ocr 1` → `study verarbeiten --limit 3 --auto` (Freigabefälle bleiben als `interrupt` offen, der Lauf geht weiter) → `study index` → `study rag-index --max 600` (Budget, weil der Embedding-Endpunkt etwa 1 Text/s schafft) → `study freigabe` (offene Freigaben ins Log) → `study briefing`. Log: `logs/daily.log`. Höchstens ein Lauf pro Tag (`DAILY_FORCE=1` erzwingt einen weiteren); Dateien pro Lauf und Index-Budget kommen aus `data/state/einstellungen.yaml`. Einrichten im Dashboard unter Agent → Zeitplan (Uhrzeit, Wochentage, ein/aus) oder mit `study zeitplan ein` bzw. [scripts/install-launchd.sh](scripts/install-launchd.sh): schreibt `~/Library/LaunchAgents/ch.fhnw.study-survivor.plist` aus den Einstellungen, lädt ihn und entlädt den alten Job `ch.fhnw.study-agent`. `study zeitplan` zeigt den Stand, `study zeitplan aus` entfernt den Job.

Lauf von Hand (moodle-dl übersprungen, kleine Budgets):

```
$ SKIP_MOODLE_DL=1 VERARBEITEN_LIMIT=1 RAG_MAX=64 scripts/daily.sh; cat logs/daily.log
=== 2026-11-09 17:17:39 ===
--- moodle-dl übersprungen (SKIP_MOODLE_DL=1)
--- convert
konvertiert: 5 · unverändert: 559 · fehlgeschlagen: 3
verarbeiten: 26HS Deep Learning BAI/Lernziele & Programm/HS26_DeepLearning_BAI.pdf
  [   0.1s] read
  [  10.9s] extract
  [  15.5s] check ok=True Beanstandungen=0
  [  15.6s] write
  [  15.6s] done
  Runden: 1 · Prüfung ok: True · Folien: 0/2
  geschrieben: termine: 14 neu
--- verarbeiten: Exit 0 (3 = Freigabe offen)
--- index
indexiert: 7 · unverändert: 153 · entfernt: 0
--- rag-index
Chunks: 8951 · neu eingebettet: 64 · entfernt: 0 · noch offen: 7666
--- freigaben
--- briefing
data/briefings/2026-11-09.md
2 Deadlines in ≤3 Tagen · 0 neue Dateien · 35 zu verarbeiten
=== Ende 2026-11-09 17:19:39, Fehler: 0
```

Die 3 fehlgeschlagenen Konvertierungen sind ein gescanntes PDF ohne Textebene und zwei Vorlagen aus einem hochgeladenen `.venv`-Ordner. Telegram fürs Briefing ist bewusst offen gelassen (vorerst Datei und Dashboard).

### Schritt 7: Vorbereitung SW9 (Evaluation, Safeguarding)

25 Testfragen, 5 pro Gruppe (termine, inhalt, pruefung, organisation, nicht zuständig), mit prüfbaren Erwartungen (Zuständigkeit, Kategorie, Tool, Stichwörter, Quelle) in [eval/testfragen.yaml](eval/testfragen.yaml). `uv run study eval [--gruppe G]` misst die Erfolgskriterien E1 bis E5 und E8 aus dem Kapitel Use Case; Antworten landen in `data/eval/` (gitignored).

Baseline vom 09.11.2026:

```
Zuständigkeit korrekt:      25/25 (100 %)
Ablehnungen korrekt:        5/5 (100 %)
Kategorie korrekt:          18/20 (90 %)
Richtiges Tool:             25/25 (100 %)
Fakten korrekt:             20/20 (100 %)
Quelle genannt:             20/20 (100 %)
Erwartete Quelle:           6/6 (100 %)
Antwortzeit Median:         8.1 s
```

Einschränkung: Die Fragen sind mit Blick auf die vorhandenen Daten geschrieben, die Baseline ist also eher optimistisch. Für SW9 (16.11.) geplant: weitere, vorher unbekannte Fragen (auch von Teamkollegen), LLM-as-a-Judge für die Antwortqualität, Safeguarding gegen Prompt Injection im Kursmaterial (Leitplanke steht im System-Prompt, noch ohne Test), Chat-Interface als SW9-Interface.
