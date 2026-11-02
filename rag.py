import os, re, hashlib
from pathlib import Path
from dotenv import load_dotenv
from getpass import getpass
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.tools import tool
from collections import Counter


load_dotenv()
if not os.environ.get("LITELLM_API_KEY"):
    os.environ["LITELLM_API_KEY"] = getpass("LITELLM_API_KEY: ")

BASE_DIR = Path(__file__).parent
DB_DIR = str(BASE_DIR / "chroma_db")
SLIDES_DIR = BASE_DIR / "data"
PROXY_BASE_URL = "https://litellm.engines.aisl.science/v1"
SIMILARITY_THRESHOLD = 0.7   # später für Folien neu testen

EMBEDDING_MODEL = "andreasmartin/apertus-v1.1-swiss-embed-0.4b"
CHUNK_SIZE, CHUNK_OVERLAP = 500, 75
PIPELINE_VERSION = 1 #hochzählen, wenn Bereinigung ändert oder neue Folien hinzugefügt werden, damit die Chroma-DB neu aufgebaut wird

NOISE = ["www.fhnw.ch/wirtschaft", "Deep Learning, HS 2026"]


embeddings = OpenAIEmbeddings(
    model=EMBEDDING_MODEL,
    base_url=PROXY_BASE_URL,
    api_key=os.environ["LITELLM_API_KEY"],
    check_embedding_ctx_length=False,
    model_kwargs={"encoding_format": None},
)

store = Chroma(collection_name="folien", embedding_function=embeddings,
               collection_metadata={"hnsw:space": "cosine"}, persist_directory=DB_DIR)

splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def remove_repeated_lines(pages, min_share=0.5):
    """Entfernt Zeilen, die in mindestens min_share der Seiten einer PDF vorkommen."""
    counts = Counter()
    for p in pages:
        counts.update(set(l.strip() for l in p.page_content.split("\n") if l.strip()))
    limit = max(3, len(pages) * min_share)
    repeated = {line for line, c in counts.items() if c >= limit}
    for p in pages:
        kept = [l for l in p.page_content.split("\n") if l.strip() not in repeated]
        p.page_content = "\n".join(kept).strip()
    return pages

def load_pdf(pdf):
    """Lädt eine PDF und bereinigt sie."""
    pages = PyPDFLoader(str(pdf)).load()
    pages = remove_repeated_lines(pages)
    for p in pages:
        text = p.page_content
        for n in NOISE:
            text = text.replace(n, "")
        text = re.sub(r"^.*HS \d{4}\s*\d*\s*$", "", text, flags=re.MULTILINE)
        p.page_content = text.strip()
        p.metadata["modul"] = pdf.stem
        p.metadata["source"] = pdf.name   # nur der Dateiname, unabhängig vom Ordner
    return pages

def load_docs():
    """Alle PDFs, für experiments.py."""
    return [p for pdf in sorted(SLIDES_DIR.glob("*.pdf")) for p in load_pdf(pdf)]
 
 
def fingerprint(pdf):
    """Ändert sich, wenn die Datei oder die Einstellungen sich ändern."""
    h = hashlib.md5(pdf.read_bytes())
    h.update(repr((NOISE, CHUNK_SIZE, CHUNK_OVERLAP, EMBEDDING_MODEL, PIPELINE_VERSION)).encode())
    return h.hexdigest()
 
 
def sync_documents():
    """Bettet nur neue oder geänderte PDFs ein und entfernt gelöschte."""
    pdfs = {pdf.name: pdf for pdf in sorted(SLIDES_DIR.glob("*.pdf"))}
    current = {name: fingerprint(pdf) for name, pdf in pdfs.items()}
    indexed = {m.get("source"): m.get("version")
               for m in store.get(include=["metadatas"])["metadatas"]}
 
    for name, version in indexed.items():
        if current.get(name) != version:          # gelöscht oder verändert
            store.delete(where={"source": name})
            print("Entfernt:", name)
 
    up_to_date = {n for n, v in indexed.items() if current.get(n) == v}
    for name, pdf in pdfs.items():
        if name in up_to_date:
            continue
        pages = load_pdf(pdf)
        for p in pages:
            p.metadata["version"] = current[name]
        chunks = splitter.split_documents(pages)
        store.add_documents(chunks)
        print(f"Eingebettet: {name} ({len(pages)} Seiten, {len(chunks)} Chunks)")
 
 
sync_documents()
 
retriever = store.as_retriever(search_type="similarity_score_threshold",
                               search_kwargs={"k": 6, "score_threshold": SIMILARITY_THRESHOLD})


@tool
def search_documents(query: str) -> str:
    """Durchsucht die Vorlesungsfolien und liefert passende Stellen mit Quelle (Modul, Folie).
    Formuliere die Suchanfrage als konkrete Stichwörter oder als Aussage im Stil der Folien,
    nicht als allgemeine Frage. Beispiel: 'Lernziele Grundbausteine neuronale Netze'
    statt 'Was sind die Ziele?'."""
    hits = retriever.invoke(query)
    if not hits:
        return "In den Folien nichts gefunden."
    return "\n\n".join(
        f"[{d.metadata['modul']}, Folie {d.metadata['page'] + 1}]\n{d.page_content}" for d in hits)