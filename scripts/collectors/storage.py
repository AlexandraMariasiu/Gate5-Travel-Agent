"""Atomic Markdown and manifest storage helpers for collected RAG documents."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

import yaml

from scripts.collectors.models import (
    FRONTMATTER_DELIMITER,
    FRONTMATTER_SEPARATOR,
    SourceDocument,
    target_path_for_document,
)

EXPECTED_FRONTMATTER_PARTS = 2

logger = logging.getLogger("collect_guides")


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via a temporary file so outputs are never half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary_path, path)


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
