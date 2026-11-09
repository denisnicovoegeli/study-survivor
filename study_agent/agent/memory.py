"""Memory (SW8): Checkpointer pro thread_id und Store mit Namespace pro Nutzer, beides in SQLite.

- Kurzzeit: AsyncSqliteSaver in data/state/memory.sqlite (Verlauf eines Threads, überlebt Neustarts).
- Langzeit: AsyncSqliteStore in derselben Datei, Namespace (user_id, "profil") mit aktuellen Kursen und Sprache.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from study_agent.config import load_settings
from study_agent.pipeline.moodle_db import MoodleDbError, current_courses


@dataclass
class Context:
    """Laufzeit-Kontext des Chat-Graphen (graph.ainvoke(..., context=Context(...)))."""
    user_id: str = "stirling"


def db_path():
    settings = load_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "memory.sqlite"


@asynccontextmanager
async def open_memory(path=None):
    """Liefert (checkpointer, store), beide offen für die Dauer des Kontexts."""
    path = str(path or db_path())
    async with AsyncSqliteSaver.from_conn_string(path) as saver, \
            AsyncSqliteStore.from_conn_string(path) as store:
        await saver.setup()
        await store.setup()
        yield saver, store


def default_profil() -> dict:
    settings = load_settings()
    try:
        kurse = [c.name for c in current_courses(settings.moodle_db, date.today())]
    except MoodleDbError:
        kurse = []
    return {"kurse": kurse, "sprache": "Deutsch (Schweiz)"}


async def get_profil(store, user_id: str) -> dict:
    """Profil aus dem Store; beim ersten Aufruf mit den aktuellen Kursen angelegt."""
    item = await store.aget((user_id, "profil"), "profil")
    if item is not None:
        return item.value
    profil = default_profil()
    await store.aput((user_id, "profil"), "profil", profil)
    return profil


async def set_profil(store, user_id: str, **changes) -> dict:
    profil = await get_profil(store, user_id)
    profil.update({k: v for k, v in changes.items() if v is not None})
    await store.aput((user_id, "profil"), "profil", profil)
    return profil
