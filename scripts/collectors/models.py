"""Source document model and filename utilities for RAG data collection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

import yaml

VALID_SOURCE_TYPES = ("official_guide", "travel_blog", "community_forum")
MINIMUM_CONTENT_LENGTH = 200
MAX_SLUG_LENGTH = 80
FRONTMATTER_DELIMITER = "---\n"
FRONTMATTER_SEPARATOR = "\n---\n"


@dataclass(frozen=True)
class SourceDocument:
    """Normalized RAG source document with traceability metadata."""

    document_id: str
    title: str
    city: str
    topic: str
    source_type: str
    source_url: str
    updated_at: str
    retrieved_at: str
    license: str
    content: str

    def __post_init__(self) -> None:
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{self.source_type}'. "
                f"Expected one of {VALID_SOURCE_TYPES}."
            )
        for field_name in ("document_id", "title", "city", "topic", "source_url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"Metadata field '{field_name}' must be non-empty.")
        stripped_length = len(self.content.strip())
        if stripped_length < MINIMUM_CONTENT_LENGTH:
            raise ValueError(
                f"Document '{self.document_id}' content too short "
                f"({stripped_length} chars < {MINIMUM_CONTENT_LENGTH})."
            )

    def metadata_dict(self) -> dict[str, str]:
        """Return frontmatter/manifest metadata without the full body text."""
        data = asdict(self)
        data.pop("content", None)
        return data

    def to_markdown(self) -> str:
        """Render the document as YAML frontmatter + clean Markdown body."""
        frontmatter = yaml.safe_dump(
            self.metadata_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).strip()
        body = self.content.strip()
        return f"{FRONTMATTER_DELIMITER}{frontmatter}{FRONTMATTER_SEPARATOR}\n{body}\n"


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Convert text into a safe, deterministic lowercase filename slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return (cleaned[:max_length].rstrip("_")) or "document"


def target_path_for_document(output_directory: Path, document: SourceDocument) -> Path:
    """Compute a deterministic path under output_directory/<source_type>/<document_id>.md."""
    filename = f"{slugify(document.document_id)}.md"
    return output_directory / document.source_type / filename
