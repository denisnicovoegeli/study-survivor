import glob, logging, re
import os
from dotenv import load_dotenv
from getpass import getpass
from langchain_community.document_loaders import PyPDFLoader, BSHTMLLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain.tools import tool

# load_dotenv liest die .env, überschreibt aber nichts, was schon gesetzt ist.
load_dotenv()

if not os.environ.get("LITELLM_API_KEY"):
    os.environ["LITELLM_API_KEY"] = getpass("LITELLM_API_KEY: ")


LLM_BASE_URL = "https://litellm.engines.aisl.science/v1"


logging.getLogger("pypdf").setLevel(logging.ERROR)  # harmlose Meldungen zum PDF ausblenden

pdf_docs = PyPDFLoader("data/General Conditions of Carriage | SWISS.pdf").load()
html_docs = [BSHTMLLoader(path, open_encoding="utf-8").load()[0]
             for path in sorted(glob.glob("data/*.html"))]

#print(len(pdf_docs), "PDF-Seiten,", len(html_docs), "Webseiten")
#print(repr(pdf_docs[34].page_content[:300]))

DIGITS = {0xF800 + i: str(i) for i in range(10)}  # Sonderzeichen → Ziffer

# neue Listen statt Änderungen an pdf_docs / html_docs: so bleibt das Original erhalten
pdf_clean = []
for doc in pdf_docs:
    lines = doc.page_content.translate(DIGITS).split("\n")
    text = "\n".join(lines[2:])  # Kopfzeilen mit Datum und Adresse weg
    pdf_clean.append(Document(page_content=text, metadata=doc.metadata))

html_clean = []
for doc in html_docs:
    text = doc.page_content.split("Main content", 1)[-1]  # Navigation weg
    text = re.sub(r"\s*\n\s*", "\n", text).strip()  # leere Zeilen weg
    html_clean.append(Document(page_content=text, metadata=doc.metadata))

docs = pdf_clean + html_clean
#print(repr(pdf_clean[34].page_content[:300]))

#print(pdf_clean[0].page_content[:300])

#print(len(docs), "Dokumente, insgesamt vor dem Splitten")
#print("\n++++++++++++++++++++++++++++\n")

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
chunks = splitter.split_documents(docs)

#print(len(chunks), "Chunks")
#print(chunks[0].metadata["source"], chunks[0].page_content[:200])


embeddings1 = OpenAIEmbeddings(
    model="andreasmartin/apertus-v1.1-swiss-embed-0.4b",
    base_url=LLM_BASE_URL,
    api_key=os.environ["LITELLM_API_KEY"],
    check_embedding_ctx_length=False,        # nicht mit dem OpenAI-Tokenizer vorzerlegen
    model_kwargs={"encoding_format": None},  # der Proxy lehnt diesen Parameter ab
)

vector = embeddings1.embed_query("My flight was cancelled.")
print(len(vector), "Zahlen, die ersten fünf:", [round(x, 3) for x in vector[:5]])

store = Chroma(collection_name="swiss_docs", 
               embedding_function=embeddings1,
               collection_metadata={"hnsw:space": "cosine"},
               persist_directory="chroma_db",)

REBUILD = False  # True, wenn die Datenbank neu aufgebaut werden soll

if REBUILD:
    store.reset_collection()  # sonst kommt beim zweiten Ausführen alles doppelt hinein

if store._collection.count() == 0:
    store.add_documents(chunks)
    print(len(chunks), "Chunks neu in die Datenbank geschrieben.")
else:
    print(store._collection.count(), "Chunks schon in der Datenbank, keine Änderungen.")

QUESTION = "Wie lange habe ich Zeit um eine Beschwerde einzureichen?"

for doc, score in store.similarity_search_with_relevance_scores(QUESTION, k=3):
    print(f"Score: {score:.2f}", "\nMetadata: ", doc.metadata["source"][5:], "|", doc.page_content[:120].replace("\n", " "))

RUN_CHUNK_EXPERIMENT = False  # True, wenn die Chunks einzeln abgefragt werden sollen

if RUN_CHUNK_EXPERIMENT:
   for size in [200, 1000, 3000]:
    parts = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=size // 8).split_documents(docs)
    test_store = Chroma(collection_name=f"chunks_{size}", embedding_function=embeddings1,
                        collection_metadata={"hnsw:space": "cosine"})
    test_store.reset_collection()
    test_store.add_documents(parts)
    best = test_store.similarity_search(QUESTION, k=1)[0]
    print(f"=== chunk_size={size}: {len(parts)} Chunks, Treffer mit {len(best.page_content)} Zeichen ===")
    print(best.page_content[:400], "\n") 

SIMILARITY_THRESHOLD = 0.5  # nur Treffer mit mindestens diesem Score werden zurückgegeben

retriever = store.as_retriever(
    search_type="similarity_score_threshold", 
    search_kwargs={"k": 4, "score_threshold": SIMILARITY_THRESHOLD}
)

@tool
def search_documents(query: str) -> str:
    """Durchsucht die Unterlagen von SWISS: Beförderungsbedingungen, Rückerstattung,
    Passagierrechte (EU 261), Handgepäck und Sportgepäck.
    Die Unterlagen sind englisch, formuliere die Suchanfrage auf Englisch.
    """
    hits = retriever.invoke(query)
    if not hits:
        return "In den Dokumenten nichts gefunden."
    return "\n\n".join(f"[{doc.metadata['source'][5:]}]\n{doc.page_content}" for doc in hits)


print(search_documents.invoke({"query": QUESTION})[:300], "\n")
print(search_documents.invoke({"query": "SWISS direct flights Zurich Bangkok"}))