"""
Collect traceable RAG travel sources into data/rag_sources/.

Saves clean Markdown documents with YAML frontmatter metadata
(title, city, topic, source_type, source_url, updated_at, retrieved_at, license)
from three source categories:
  1. official_guide  - Wikivoyage via MediaWiki API
  2. travel_blog     - Curated travel articles via trafilatura / BeautifulSoup
  3. community_forum - Reddit threads via OAuth API or Arctic Shift archive fallback

Usage:
    python scripts/collect_guides.py --city Rome --sources all
    python scripts/collect_guides.py --sources wikivoyage --dry-run
    python scripts/collect_guides.py --sources reddit --min-reddit-score 25 --overwrite
"""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
import sys
from typing import Callable, Optional

import requests

# Allow running directly as `python scripts/collect_guides.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.collectors import (
    SourceDocument,
    build_http_session,
    collect_reddit,
    collect_travel_blogs,
    collect_wikivoyage,
    save_documents,
    write_manifest,
)
from src.config import PROTOTYPE_CITY

DEFAULT_OUTPUT_DIRECTORY = REPO_ROOT / "data" / "rag_sources"
DEFAULT_MINIMUM_REDDIT_SCORE = 25

logger = logging.getLogger("collect_guides")


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
        default=DEFAULT_MINIMUM_REDDIT_SCORE,
        help=f"Minimum post upvote score for Reddit threads (default: {DEFAULT_MINIMUM_REDDIT_SCORE}).",
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
                    minimum_score=options.min_reddit_score,
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
