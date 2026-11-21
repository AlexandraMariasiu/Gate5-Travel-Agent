from pathlib import Path
import pytest

from src.config import RAG_SOURCES_DIR
from src.rag import ingestion, retrieval


SAMPLE_DOC = """---
document_id: Rome_test_guide
title: 'Rome Test Guide: Transport'
city: Rome
topic: getting_around
source_type: official_guide
source_url: https://example.org/rome-transport
---

# Getting Around

Buses and trams cover most neighborhoods. Buy tickets before boarding.

## Metro

Rome has three metro lines: A, B, and C. Validate your ticket at the gate.
"""


def test_parse_markdown_document_extracts_frontmatter_and_body(tmp_path: Path):
    doc = tmp_path / "official_guide" / "transport.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(SAMPLE_DOC, encoding="utf-8")

    meta, body = ingestion.parse_markdown_document(doc, sources_dir=tmp_path)

    assert meta["document_id"] == "Rome_test_guide"
    assert meta["title"] == "Rome Test Guide: Transport"
    assert meta["topic"] == "getting_around"
    assert meta["source_url"] == "https://example.org/rome-transport"
    assert meta["file_path"] == "official_guide/transport.md"
    assert "---" not in body
    assert body.startswith("# Getting Around")


def test_chunk_document_preserves_metadata_and_sections(tmp_path: Path):
    doc = tmp_path / "official_guide" / "transport.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(SAMPLE_DOC, encoding="utf-8")

    chunks = ingestion.chunk_document(doc, sources_dir=tmp_path, chunk_size=400, chunk_overlap=50)

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "Rome_test_guide::chunk_0000"
    assert chunks[1].chunk_id == "Rome_test_guide::chunk_0001"
    assert chunks[0].metadata["section"] == "Getting Around"
    assert chunks[1].metadata["section"] == "Metro"
    assert all(c.metadata["source_url"] == "https://example.org/rome-transport" for c in chunks)
    assert "Rome Test Guide: Transport — Metro" in chunks[1].text


def test_chunk_document_splits_oversized_paragraphs_within_limit(tmp_path: Path):
    long_sentences = " ".join(
        [f"Sentence number {i} gives practical Rome travel advice." for i in range(30)]
    )
    doc = tmp_path / "travel_blog" / "long.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "---\n"
        "document_id: long_doc\n"
        "title: Long Guide\n"
        "source_type: travel_blog\n"
        "source_url: https://example.org/long\n"
        "---\n\n"
        f"## Tips\n\n{long_sentences}\n",
        encoding="utf-8",
    )

    chunks = ingestion.chunk_document(doc, sources_dir=tmp_path, chunk_size=300, chunk_overlap=40)

    assert len(chunks) > 2
    assert all(len(c.text) <= 300 for c in chunks)


@pytest.mark.parametrize("size,overlap", [(0, 0), (-10, 0), (100, -1), (100, 100)])
def test_chunk_document_rejects_invalid_sizes(tmp_path: Path, size: int, overlap: int):
    doc = tmp_path / "doc.md"
    doc.write_text(SAMPLE_DOC, encoding="utf-8")

    with pytest.raises(ValueError):
        ingestion.chunk_document(doc, sources_dir=tmp_path, chunk_size=size, chunk_overlap=overlap)


def test_load_and_chunk_real_rag_sources():
    chunks = ingestion.load_and_chunk_documents(RAG_SOURCES_DIR)

    assert len(chunks) > 36
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for chunk in chunks:
        assert chunk.text.strip()
        assert chunk.metadata["title"]
        assert chunk.metadata["source_url"]
        assert chunk.metadata["source_type"] in {
            "official_guide",
            "travel_blog",
            "community_forum",
        }


class _FakeCollection:
    def __init__(self):
        self.upserts = []
        self.stored_count = 0
        self.query_calls = []
        self.query_response = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    def upsert(self, ids, documents, metadatas, embeddings):
        self.upserts.append((ids, documents, metadatas, embeddings))
        self.stored_count += len(ids)

    def count(self):
        return self.stored_count

    def query(self, query_embeddings, n_results, include):
        self.query_calls.append((query_embeddings, n_results, include))
        return self.query_response


def test_ingest_documents_upserts_batches_with_metadata(tmp_path: Path, monkeypatch):
    doc = tmp_path / "official_guide" / "transport.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(SAMPLE_DOC, encoding="utf-8")

    fake_collection = _FakeCollection()
    monkeypatch.setattr(ingestion, "get_chroma_collection", lambda **_: fake_collection)
    monkeypatch.setattr(
        ingestion,
        "embed_texts",
        lambda texts, model_name=None: [[0.1, 0.2, 0.3] for _ in texts],
    )

    total = ingestion.ingest_documents(
        sources_dir=tmp_path,
        persist_dir=tmp_path / "chroma_db",
        batch_size=1,
    )

    assert total == 2
    assert len(fake_collection.upserts) == 2
    assert fake_collection.upserts[0][0] == ["Rome_test_guide::chunk_0000"]
    assert fake_collection.upserts[1][0] == ["Rome_test_guide::chunk_0001"]


def test_search_travel_notes_returns_top_k_with_traceable_sources(monkeypatch):
    fake_collection = _FakeCollection()
    fake_collection.stored_count = 2
    fake_collection.query_response = {
        "ids": [["Rome_test_guide::chunk_0001", "Rome_test_guide::chunk_0000"]],
        "documents": [["Metro lines A, B, C", "Buses and trams"]],
        "metadatas": [
            [
                {
                    "document_id": "Rome_test_guide",
                    "title": "Rome Test Guide: Transport",
                    "section": "Metro",
                    "source_type": "official_guide",
                    "topic": "getting_around",
                    "source_url": "https://example.org/rome-transport",
                    "file_path": "official_guide/transport.md",
                },
                {
                    "document_id": "Rome_test_guide",
                    "title": "Rome Test Guide: Transport",
                    "section": "Getting Around",
                    "source_type": "official_guide",
                    "topic": "getting_around",
                    "source_url": "https://example.org/rome-transport",
                    "file_path": "official_guide/transport.md",
                },
            ]
        ],
        "distances": [[0.15, 0.32]],
    }

    monkeypatch.setattr(retrieval, "get_chroma_collection", lambda **_: fake_collection)
    monkeypatch.setattr(retrieval, "embed_texts", lambda texts, model_name=None: [[0.5, 0.5]])

    results = retrieval.search_travel_notes("How do I use the metro in Rome?")

    # Default top_k=4 is clamped to stored_count=2
    assert fake_collection.query_calls[0][1] == 2
    assert len(results) == 2
    assert results[0]["score"] == 0.85
    assert results[0]["title"] == "Rome Test Guide: Transport"
    assert results[0]["section"] == "Metro"
    assert results[0]["source_url"] == "https://example.org/rome-transport"
    assert results[0]["text"] == "Metro lines A, B, C"


def test_search_travel_notes_empty_collection_returns_empty_list(monkeypatch):
    fake_collection = _FakeCollection()
    monkeypatch.setattr(retrieval, "get_chroma_collection", lambda **_: fake_collection)

    assert retrieval.search_travel_notes("getting around Rome") == []


@pytest.mark.parametrize("query,top_k", [("", 4), ("   ", 4), ("Rome", 0), ("Rome", -2)])
def test_search_travel_notes_validates_inputs(query: str, top_k: int):
    with pytest.raises(ValueError):
        retrieval.search_travel_notes(query, top_k=top_k)


def test_format_results_includes_title_and_source():
    formatted = retrieval.format_results(
        [
            {
                "score": 0.85,
                "title": "Rome Test Guide",
                "section": "Metro",
                "source_url": "https://example.org/rome",
                "file_path": "official_guide/transport.md",
                "source_type": "official_guide",
                "text": "Validate your ticket.",
            }
        ]
    )

    assert "Rome Test Guide | Section: Metro" in formatted
    assert "https://example.org/rome" in formatted
    assert "Validate your ticket." in formatted
