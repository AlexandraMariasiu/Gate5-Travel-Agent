"""Semantic search over ingested travel notes in ChromaDB."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.config import (
    CHROMA_DB_DIR,
    EMBEDDING_MODEL_NAME,
    RAG_COLLECTION_NAME,
    RAG_TOP_K,
)
from src.rag.ingestion import embed_texts, get_chroma_collection


def search_travel_notes(
    query: str,
    top_k: int = RAG_TOP_K,
    persist_dir: Path | str = CHROMA_DB_DIR,
    collection_name: str = RAG_COLLECTION_NAME,
    model_name: str = EMBEDDING_MODEL_NAME,
) -> list[dict[str, Any]]:
    """Retrieve the top-k most relevant travel note chunks with source metadata."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("Query must not be empty.")
    if top_k <= 0:
        raise ValueError("top_k must be positive.")

    collection = get_chroma_collection(
        persist_dir=persist_dir,
        collection_name=collection_name,
        reset=False,
    )

    total_chunks = collection.count()
    if total_chunks == 0:
        return []

    # Reuse embed_texts so query vectors match the document normalization and model
    query_embedding = embed_texts([cleaned_query], model_name=model_name)[0]

    # Clamp n_results to total_chunks so ChromaDB does not fail on small test indexes
    n_results = min(top_k, total_chunks)
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: list[dict[str, Any]] = []
    for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances):
        meta = meta or {}
        # Collection uses cosine space, so similarity is 1 - cosine_distance
        score = round(1.0 - float(distance), 4)
        results.append(
            {
                "chunk_id": chunk_id,
                "text": text,
                "score": score,
                "document_id": meta.get("document_id", ""),
                "title": meta.get("title", ""),
                "section": meta.get("section", ""),
                "source_type": meta.get("source_type", ""),
                "topic": meta.get("topic", ""),
                "source_url": meta.get("source_url", ""),
                "file_path": meta.get("file_path", ""),
            }
        )

    return results


def format_results(results: list[dict[str, Any]]) -> str:
    """Format retrieved chunks with traceable sources for terminal inspection."""
    if not results:
        return (
            "No matching travel notes found. "
            "Have you run `python -m src.rag.ingestion`?"
        )

    lines: list[str] = []
    for idx, item in enumerate(results, start=1):
        section = f" | Section: {item['section']}" if item.get("section") else ""
        lines.append(
            f"[{idx}] score={item['score']:.4f} | {item['title']}{section}\n"
            f"    source: {item['source_url'] or item['file_path']} ({item['source_type']})\n"
            f"    {item['text']}"
        )
    return "\n\n".join(lines)


def main() -> None:
    """CLI entrypoint to query the ChromaDB travel notes index."""
    parser = argparse.ArgumentParser(
        description="Search Rome travel notes stored in ChromaDB."
    )
    parser.add_argument("query", type=str, help="Travel question to search for.")
    parser.add_argument("--top-k", type=int, default=RAG_TOP_K)
    parser.add_argument("--persist-dir", type=Path, default=CHROMA_DB_DIR)
    parser.add_argument("--collection", type=str, default=RAG_COLLECTION_NAME)
    parser.add_argument("--model", type=str, default=EMBEDDING_MODEL_NAME)
    args = parser.parse_args()

    results = search_travel_notes(
        query=args.query,
        top_k=args.top_k,
        persist_dir=args.persist_dir,
        collection_name=args.collection,
        model_name=args.model,
    )
    print(format_results(results))


if __name__ == "__main__":
    main()
