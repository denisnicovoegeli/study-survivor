"""Hybrid Retrieval über das Kursmaterial (SW7).

- Sparse: bestehende SQLite-FTS5-Suche mit BM25 (`pipeline/suche.py`, state/suche.db).
- Dense: Chroma mit Embeddings über den LiteLLM der FHNW (state/chroma).
- Zusammenführung mit Reciprocal Rank Fusion (RRF, k=60).

Chunking: dieselben Abschnitte wie die FTS-Suche (eine Folie bzw. Seite), lange
Abschnitte werden mit RecursiveCharacterTextSplitter geteilt. Pro Abschnitt
höchstens MAX_CHUNKS Chunks, damit grosse Textdumps den Index nicht fluten.
"""
import hashlib
import sqlite3
from dataclasses import dataclass

from study_agent.config import Settings, load_settings
from study_agent.pipeline.suche import index_db_path, search

COLLECTION = "kursmaterial"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
MAX_CHUNKS = 4
RRF_K = 60
BATCH = 64


@dataclass
class Fundstelle:
    kurs: str
    datei: str
    folie: str
    text: str
    score: float
    via: list[str]

    def quelle(self) -> str:
        from pathlib import Path
        art = "Folie" if self.folie else "Datei"
        return f"{self.kurs} / {Path(self.datei).name}" + (f" / {art} {self.folie}" if self.folie else "")


def _chroma_dir(settings: Settings):
    return settings.state_dir / "chroma"


def vectorstore(settings: Settings | None = None):
    from langchain_chroma import Chroma

    from study_agent.llm import embeddings

    settings = settings or load_settings()
    return Chroma(collection_name=COLLECTION, embedding_function=embeddings(),
                  persist_directory=str(_chroma_dir(settings)))


def _chunk_id(datei: str, folie: str, i: int) -> str:
    return hashlib.sha1(f"{datei}#{folie}#{i}".encode()).hexdigest()


def build_dense_index(settings: Settings | None = None, force: bool = False, kurs: str | None = None,
                      log=print) -> dict:
    """Liest die Abschnitte aus der FTS-Tabelle und bettet neue Chunks ein (inkrementell über die ID)."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    settings = settings or load_settings()
    db = index_db_path(settings.state_dir)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT kurs, datei, folie, text FROM suche").fetchall()
    con.close()

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks: dict[str, tuple[str, dict]] = {}
    for kurs_, datei, folie, text in rows:
        if kurs and kurs.casefold() not in kurs_.casefold():
            continue
        for i, part in enumerate(splitter.split_text(text)[:MAX_CHUNKS]):
            chunks[_chunk_id(datei, folie, i)] = (part, {"kurs": kurs_, "datei": datei, "folie": folie})

    vs = vectorstore(settings)
    got = vs.get(include=["metadatas"])
    # bei Kursfilter nur die Chunks dieses Kurses abgleichen
    existing = {cid for cid, m in zip(got["ids"], got["metadatas"])
                if not kurs or kurs.casefold() in (m or {}).get("kurs", "").casefold()}
    if force:
        if existing:
            vs.delete(ids=list(existing))
        existing = set()
    neu = [cid for cid in chunks if cid not in existing]
    alt = [cid for cid in existing if cid not in chunks]
    if alt:
        vs.delete(ids=alt)
    for start in range(0, len(neu), BATCH):
        batch = neu[start:start + BATCH]
        vs.add_texts([chunks[c][0] for c in batch], metadatas=[chunks[c][1] for c in batch], ids=batch)
        log(f"  eingebettet {min(start + BATCH, len(neu))}/{len(neu)}")
    return {"chunks": len(chunks), "neu": len(neu), "entfernt": len(alt)}


def hybrid_search(frage: str, kurs: str | None = None, k: int = 5, settings: Settings | None = None,
                  fetch: int = 20) -> list[Fundstelle]:
    """Dense (Chroma) und sparse (FTS5/BM25) je `fetch` Treffer, dann RRF: score = Σ 1/(k + rang)."""
    settings = settings or load_settings()
    fused: dict[tuple[str, str], Fundstelle] = {}

    def add(key, kurs_, datei, folie, text, rank, via):
        f = fused.get(key)
        if f is None:
            f = fused[key] = Fundstelle(kurs_, datei, folie, text, 0.0, [])
        f.score += 1.0 / (RRF_K + rank)
        if via not in f.via:
            f.via.append(via)

    # sparse
    for rank, t in enumerate(search(index_db_path(settings.state_dir), frage, course=kurs, limit=fetch), 1):
        add((t.datei, t.folie), t.kurs, t.datei, t.folie, t.text, rank, "bm25")

    # dense (Kursfilter nachträglich, da Chroma kein LIKE kennt)
    if _chroma_dir(settings).exists():
        docs = vectorstore(settings).similarity_search(frage, k=fetch * (3 if kurs else 1))
        if kurs:
            docs = [d for d in docs if kurs.casefold() in d.metadata.get("kurs", "").casefold()]
        seen = set()
        rank = 0
        for d in docs:
            key = (d.metadata["datei"], d.metadata["folie"])
            if key in seen:  # mehrere Chunks desselben Abschnitts: bester Rang zählt
                continue
            seen.add(key)
            rank += 1
            add(key, d.metadata["kurs"], key[0], key[1], d.page_content, rank, "dense")
            if rank >= fetch:
                break

    return sorted(fused.values(), key=lambda f: f.score, reverse=True)[:k]
