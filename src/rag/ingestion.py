"""Load Markdown travel documents and split them into traceable chunks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import yaml

from src.config import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE, RAG_SOURCES_DIR

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class DocumentChunk:
    """One text chunk with deterministic ID and Chroma-compatible metadata."""

    chunk_id: str
    text: str
    metadata: dict[str, str | int]


def parse_markdown_document(
    path: Path | str,
    sources_dir: Path | str = RAG_SOURCES_DIR,
) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter and Markdown body from a RAG source file."""
    path = Path(path)
    sources_dir = Path(sources_dir)
    raw = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    body = raw

    # Extract YAML frontmatter between opening and closing --- lines
    if raw.startswith("---"):
        lines = raw.splitlines(keepends=True)
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is not None:
            frontmatter_text = "".join(lines[1:end_idx])
            parsed = yaml.safe_load(frontmatter_text) or {}
            if isinstance(parsed, dict):
                # Chroma metadata only accepts scalar primitives, so stringify YAML values
                metadata = {
                    str(k): str(v) for k, v in parsed.items() if v is not None
                }
            body = "".join(lines[end_idx + 1 :])

    # Use a portable POSIX relative path for traceable source citations
    try:
        rel_path = path.resolve().relative_to(sources_dir.resolve()).as_posix()
    except ValueError:
        rel_path = path.name

    metadata.setdefault("document_id", path.stem)
    metadata.setdefault("title", path.stem)
    metadata.setdefault("source_type", path.parent.name)
    metadata.setdefault("source_url", "")
    metadata.setdefault("topic", "")
    metadata.setdefault("city", "")
    metadata["file_path"] = rel_path
    return metadata, body.strip()


def _split_by_headings(body: str) -> list[tuple[str, str]]:
    """Split Markdown text into (section_heading, section_body) pairs."""
    sections: list[tuple[str, str]] = []
    current_section = ""
    buffer: list[str] = []

    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            # Flush the accumulated section body before switching headings
            content = "\n".join(buffer).strip()
            if content:
                sections.append((current_section, content))
            current_section = match.group(2).strip()
            buffer = []
        else:
            buffer.append(line)

    trailing = "\n".join(buffer).strip()
    if trailing:
        sections.append((current_section, trailing))
    return sections


def _split_oversized_block(text: str, max_chars: int) -> list[str]:
    """Split a long paragraph along sentence or word boundaries."""
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            # Fall back to word-level splitting when a single sentence exceeds max_chars
            if current:
                pieces.append(current)
                current = ""
            words = sentence.split()
            word_buf = ""
            for word in words:
                candidate = f"{word_buf} {word}".strip() if word_buf else word
                if len(candidate) <= max_chars:
                    word_buf = candidate
                else:
                    if word_buf:
                        pieces.append(word_buf)
                    word_buf = word
            if word_buf:
                pieces.append(word_buf)
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = sentence

    if current:
        pieces.append(current)
    return pieces


def _tail_overlap(text: str, overlap: int) -> str:
    """Return up to `overlap` trailing characters snapped to a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    snippet = text[-overlap:]
    # Snap to the next space so the overlapped prefix does not start mid-word
    space_idx = snippet.find(" ")
    if space_idx != -1 and space_idx + 1 < len(snippet):
        return snippet[space_idx + 1 :].strip()
    return snippet.strip()


def _pack_section_text(
    section_text: str,
    max_chars: int,
    overlap: int,
) -> list[str]:
    """Pack paragraphs in a section into overlapping chunks <= `max_chars`."""
    raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section_text) if p.strip()]
    blocks: list[str] = []
    for para in raw_paragraphs:
        blocks.extend(_split_oversized_block(para, max_chars))

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
                carry = _tail_overlap(current, overlap)
                # Ensure carry + block still fits inside max_chars
                if carry and len(carry) + 2 + len(block) <= max_chars:
                    current = f"{carry}\n\n{block}"
                else:
                    current = block
            else:
                current = block

    if current:
        chunks.append(current)
    return chunks


def chunk_document(
    path: Path | str,
    sources_dir: Path | str = RAG_SOURCES_DIR,
    chunk_size: int = RAG_CHUNK_SIZE,
    chunk_overlap: int = RAG_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Load one Markdown file and split it into `DocumentChunk` objects."""
    path = Path(path)
    sources_dir = Path(sources_dir)
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

    metadata, body = parse_markdown_document(path, sources_dir=sources_dir)
    if not body:
        return []

    title = metadata["title"]
    doc_id = metadata["document_id"]
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    for section, section_body in _split_by_headings(body):
        # Include title/section in chunk text so embeddings keep topic context
        header = f"{title} — {section}" if section and section != title else title
        prefix = f"{header}\n\n"
        # Reserve space for the context header so total chunk length stays bounded
        available = max(chunk_size - len(prefix), min(200, chunk_size))
        # Cap overlap so short sections are not mostly repeated text
        effective_overlap = min(chunk_overlap, available // 3)

        for body_piece in _pack_section_text(section_body, available, effective_overlap):
            chunk_meta: dict[str, str | int] = {
                "document_id": doc_id,
                "title": title,
                "city": metadata.get("city", ""),
                "topic": metadata.get("topic", ""),
                "source_type": metadata.get("source_type", ""),
                "source_url": metadata.get("source_url", ""),
                "file_path": metadata.get("file_path", path.name),
                "section": section,
                "chunk_index": chunk_index,
            }
            chunks.append(
                DocumentChunk(
                    # Deterministic ID keeps repeated ingestion idempotent on upsert
                    chunk_id=f"{doc_id}::chunk_{chunk_index:04d}",
                    text=f"{prefix}{body_piece}",
                    metadata=chunk_meta,
                )
            )
            chunk_index += 1

    return chunks


def load_and_chunk_documents(
    sources_dir: Path | str = RAG_SOURCES_DIR,
    chunk_size: int = RAG_CHUNK_SIZE,
    chunk_overlap: int = RAG_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Load and chunk all Markdown documents under `sources_dir`."""
    sources_dir = Path(sources_dir)
    if not sources_dir.exists():
        raise FileNotFoundError(f"RAG sources directory not found: {sources_dir}")

    all_chunks: list[DocumentChunk] = []
    for md_path in sorted(sources_dir.rglob("*.md")):
        all_chunks.extend(
            chunk_document(
                md_path,
                sources_dir=sources_dir,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return all_chunks
