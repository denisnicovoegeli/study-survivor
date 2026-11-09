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
