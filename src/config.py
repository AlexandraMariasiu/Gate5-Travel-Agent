from pathlib import Path

PROTOTYPE_CITY = "Rome"

BASE_DIR = Path(__file__).resolve().parent.parent
RAG_SOURCES_DIR = BASE_DIR / "data" / "rag_sources"
CHROMA_DB_DIR = BASE_DIR / "chroma_db"
RAG_COLLECTION_NAME = "travel_notes"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
RAG_CHUNK_SIZE = 800
RAG_CHUNK_OVERLAP = 120
RAG_TOP_K = 4
