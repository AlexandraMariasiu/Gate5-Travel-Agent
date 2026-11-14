"""
Collect traceable RAG travel sources into data/rag_sources/.

Saves clean Markdown documents with YAML frontmatter metadata
(title, city, topic, source_type, source_url, updated_at, retrieved_at, license)
from three source categories:
  1. official_guide  - Wikivoyage via MediaWiki API
  2. travel_blog     - Curated travel articles via trafilatura / BeautifulSoup
  3. community_forum - Reddit threads via public JSON endpoints

Usage:
    python scripts/collect_guides.py --city Rome --sources all
    python scripts/collect_guides.py --sources wikivoyage --dry-run
    python scripts/collect_guides.py --sources reddit --min-reddit-score 25 --overwrite
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable, Iterable, Optional

import requests
import yaml

# Allow running directly as `python scripts/collect_guides.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import PROTOTYPE_CITY

VALID_SOURCE_TYPES = ("official_guide", "travel_blog", "community_forum")
DEFAULT_OUTPUT_DIRECTORY = REPO_ROOT / "data" / "rag_sources"
USER_AGENT = (
    "Gate5TravelAgent/0.1 (Academic Travel RAG Project; "
    "Python requests; non-commercial research)"
)
MINIMUM_CONTENT_LENGTH = 200
MAX_SLUG_LENGTH = 80
REQUEST_TIMEOUT_SECONDS = 20
MAX_FETCH_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUS_CODES = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
DEFAULT_MIN_REDDIT_SCORE = 25
FRONTMATTER_DELIMITER = "---\n"
FRONTMATTER_SEPARATOR = "\n---\n"
EXPECTED_FRONTMATTER_PARTS = 2

logger = logging.getLogger("collect_guides")


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


def build_http_session(user_agent: str = USER_AGENT) -> requests.Session:
    """Create a requests.Session with explicit User-Agent headers."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def fetch_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    max_retries: int = MAX_FETCH_RETRIES,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> requests.Response:
    """Fetch a URL with basic retry/backoff handling for transient errors."""
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout_seconds)
            if response.status_code in RETRYABLE_STATUS_CODES:
                wait_seconds = backoff_seconds * attempt
                logger.warning(
                    "HTTP %s for %s (attempt %d/%d); retrying in %.1fs",
                    response.status_code,
                    url,
                    attempt,
                    max_retries,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < max_retries:
                wait_seconds = backoff_seconds * attempt
                logger.warning(
                    "Request error for %s (attempt %d/%d): %s; retrying in %.1fs",
                    url,
                    attempt,
                    max_retries,
                    error,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts: {last_error}")


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via a temporary file so outputs are never half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary_path, path)


def target_path_for_document(output_directory: Path, document: SourceDocument) -> Path:
    """Compute a deterministic path under output_directory/<source_type>/<document_id>.md."""
    filename = f"{slugify(document.document_id)}.md"
    return output_directory / document.source_type / filename


def save_documents(
    documents: Iterable[SourceDocument],
    output_directory: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    """Save validated documents safely without duplicates or corrupted files."""
    saved_entries: list[dict[str, str]] = []
    seen_document_ids: set[str] = set()

    for document in documents:
        if document.document_id in seen_document_ids:
            logger.warning("Skipping duplicate document_id in batch: %s", document.document_id)
            continue
        seen_document_ids.add(document.document_id)

        destination_path = target_path_for_document(output_directory, document)
        relative_path = destination_path.relative_to(output_directory).as_posix()

        entry = document.metadata_dict()
        entry["file_path"] = relative_path

        if destination_path.exists() and not overwrite:
            logger.info("Skipping existing file (use --overwrite to refresh): %s", relative_path)
            saved_entries.append(entry)
            continue

        if dry_run:
            logger.info(
                "[DRY RUN] Would write %s (%d chars)",
                relative_path,
                len(document.content),
            )
            saved_entries.append(entry)
            continue

        atomic_write_text(destination_path, document.to_markdown())
        logger.info("Saved %s (%d chars)", relative_path, len(document.content))
        saved_entries.append(entry)

    return saved_entries


def write_manifest(
    output_directory: Path,
    city: str,
    retrieved_at: str,
    *,
    dry_run: bool = False,
) -> None:
    """Build manifest.json by scanning saved Markdown frontmatter in output_directory."""
    records: list[dict[str, str]] = []
    for markdown_path in sorted(output_directory.glob("*/*.md")):
        raw_text = markdown_path.read_text(encoding="utf-8")
        if not raw_text.startswith(FRONTMATTER_DELIMITER):
            continue
        parts = raw_text.split(FRONTMATTER_SEPARATOR, 1)
        if len(parts) != EXPECTED_FRONTMATTER_PARTS:
            continue
        frontmatter_text = parts[0].removeprefix(FRONTMATTER_DELIMITER)
        metadata = yaml.safe_load(frontmatter_text) or {}
        metadata["file_path"] = markdown_path.relative_to(output_directory).as_posix()
        records.append(metadata)

    manifest = {
        "city": city,
        "updated_at": retrieved_at,
        "document_count": len(records),
        "documents": records,
    }
    manifest_path = output_directory / "manifest.json"
    if dry_run:
        logger.info("[DRY RUN] Would update manifest.json (%d records)", len(records))
        return
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    logger.info("Updated %s (%d documents indexed)", manifest_path, len(records))


def collect_wikivoyage(
    session: requests.Session,
    city: str,
    retrieved_at: str,
) -> list[SourceDocument]:
    """Collect structured travel guide sections from Wikivoyage."""
    logger.info("Wikivoyage collector is not implemented yet.")
    return []


def collect_travel_blogs(
    session: requests.Session,
    city: str,
    retrieved_at: str,
) -> list[SourceDocument]:
    """Collect clean Markdown articles from curated travel blogs."""
    logger.info("Travel blog collector is not implemented yet.")
    return []


def collect_reddit(
    session: requests.Session,
    city: str,
    retrieved_at: str,
    *,
    min_score: int = DEFAULT_MIN_REDDIT_SCORE,
) -> list[SourceDocument]:
    """Collect top-voted Reddit discussions and comments."""
    logger.info("Reddit collector is not implemented yet.")
    return []


def parse_arguments(arguments: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line options for the RAG source collection script."""
    parser = argparse.ArgumentParser(
        description="Collect traceable RAG travel guide sources for Gate5."
    )
    parser.add_argument(
        "--city",
        default=PROTOTYPE_CITY,
        help=f"Target city to collect guides for (default: {PROTOTYPE_CITY}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"Directory for collected Markdown files (default: {DEFAULT_OUTPUT_DIRECTORY}).",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=("all", "wikivoyage", "blogs", "reddit"),
        default=["all"],
        help="Which source collectors to run (default: all).",
    )
    parser.add_argument(
        "--min-reddit-score",
        type=int,
        default=DEFAULT_MIN_REDDIT_SCORE,
        help=f"Minimum post upvote score for Reddit threads (default: {DEFAULT_MIN_REDDIT_SCORE}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing Markdown files instead of skipping them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate documents without writing files to disk.",
    )
    return parser.parse_args(arguments)


def main(arguments: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    options = parse_arguments(arguments)
    retrieved_at = date.today().isoformat()
    selected_sources = set(options.sources)
    run_all = "all" in selected_sources

    session = build_http_session()
    collectors: list[tuple[str, Callable[[], list[SourceDocument]]]] = []

    if run_all or "wikivoyage" in selected_sources:
        collectors.append(
            ("wikivoyage", lambda: collect_wikivoyage(session, options.city, retrieved_at))
        )
    if run_all or "blogs" in selected_sources:
        collectors.append(
            ("blogs", lambda: collect_travel_blogs(session, options.city, retrieved_at))
        )
    if run_all or "reddit" in selected_sources:
        collectors.append(
            (
                "reddit",
                lambda: collect_reddit(
                    session,
                    options.city,
                    retrieved_at,
                    min_score=options.min_reddit_score,
                ),
            )
        )

    all_documents: list[SourceDocument] = []
    for collector_name, collector in collectors:
        logger.info("Running collector: %s (city=%s)", collector_name, options.city)
        try:
            documents = collector()
            logger.info(
                "Collector '%s' produced %d valid document(s).",
                collector_name,
                len(documents),
            )
            all_documents.extend(documents)
        except Exception as error:
            logger.exception("Collector '%s' failed: %s", collector_name, error)

    save_documents(
        all_documents,
        options.output_dir,
        overwrite=options.overwrite,
        dry_run=options.dry_run,
    )
    write_manifest(options.output_dir, options.city, retrieved_at, dry_run=options.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
