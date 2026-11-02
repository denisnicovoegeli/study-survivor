import re
from langchain_community.retrievers import BM25Retriever
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

# Aus rag.py: Embedding-Modell und Pfade. Die Folien-DB wird dort nur gebaut, wenn sie leer ist.
from rag import embeddings, BASE_DIR, load_docs, store

EXP_DIR = str(BASE_DIR / "chroma_experiments")

# (Frage, Stichwort, das im richtigen Treffer stehen muss). Stichwort = None, wenn die Antwort nicht in den Folien steht.
TESTS = [
    ("Was sind die Ziele des Moduls?", "Ziele"),
    ("Wie sieht die Prüfung in diesem Modul aus?", "Leistungsnachweis"),
    ("Was ist die Haupstadt der Schweiz?", None),
]

CONFIGS = [(200, 25), (500, 75), (1000, 150)]   # (chunk_size, chunk_overlap)
K = 3



def get_store(size, overlap, docs):
    """Öffnet die Test-Collection oder baut sie beim ersten Mal auf."""
    s = Chroma(collection_name=f"folien_{size}_{overlap}", embedding_function=embeddings,
               collection_metadata={"hnsw:space": "cosine"}, persist_directory=EXP_DIR)
    if s._collection.count() == 0:
        chunks = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap).split_documents(docs)
        s.add_documents(chunks)
        print(f"  (neu eingebettet: {len(chunks)} Chunks)")
    return s


def run_chunk_experiment():
    docs = load_docs()
    for size, overlap in CONFIGS:
        print(f"\n===== chunk_size={size}, overlap={overlap} =====")
        s = get_store(size, overlap, docs)
        for question, keyword in TESTS:
            hits = s.similarity_search_with_relevance_scores(question, k=K)
            best_score = hits[0][1]
            found = any(keyword.lower() in d.page_content.lower() for d, _ in hits) if keyword else None
            mark = {True: "✓", False: "✗", None: "-"}[found]
            print(f"{mark} beste Score {best_score:.2f} | {question}")
            print("    ", hits[0][0].page_content[:100].replace("\n", " "))


def run_threshold_experiment(size=500, overlap=75):
    s = get_store(size, overlap, load_docs())
    print(f"\n===== Scores des besten Treffers (chunk_size={size}) =====")
    for question, keyword in TESTS:
        score = s.similarity_search_with_relevance_scores(question, k=1)[0][1]
        group = "in Folien" if keyword else "NICHT in Folien"
        print(f"{score:.2f}  {group}: {question}")

def words(text):
    return re.findall(r"\w+", text.lower())   # Kleinbuchstaben, nur Wörter und Zahlen


def rrf(result_lists, k=3, c=60):
    """Reciprocal Rank Fusion: pro Liste 1/(c+Rang), Punkte addieren."""
    scores, docs_by_key = {}, {}
    for results in result_lists:
        for rank, doc in enumerate(results, start=1):
            key = doc.page_content
            docs_by_key[key] = doc
            scores[key] = scores.get(key, 0) + 1 / (c + rank)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [docs_by_key[key] for key, _ in ranked]


def run_retrieval_experiment(size=500, overlap=75, k=3):
    docs = load_docs()
    chunks = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap).split_documents(docs)
    dense_store = get_store(size, overlap, docs)
    bm25 = BM25Retriever.from_documents(chunks, k=10, preprocess_func=words)

    print(f"\n===== dense vs. sparse vs. hybrid (chunk_size={size}, k={k}) =====")
    for question, keyword in TESTS:
        dense = dense_store.similarity_search(question, k=10)
        sparse = bm25.invoke(question)
        hybrid = rrf([sparse, dense], k=k)

        print(f"\n{question}")
        for name, results in [("dense", dense[:k]), ("sparse", sparse[:k]), ("hybrid", hybrid)]:
            if keyword:
                rank = next((i for i, d in enumerate(results, 1) if keyword.lower() in d.page_content.lower()), None)
                mark = f"✓ Rang {rank}" if rank else "✗"
            else:
                mark = "-"
            print(f"  {name:7} {mark:9} | {results[0].page_content[:70]!r}")


if __name__ == "__main__":
    #run_chunk_experiment()
    run_threshold_experiment()
    #run_retrieval_experiment()


