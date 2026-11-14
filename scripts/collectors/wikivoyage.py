"""Wikivoyage official_guide collector using the MediaWiki API."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup, Tag
import requests

from scripts.collectors.http_client import fetch_with_retries
from scripts.collectors.models import MINIMUM_CONTENT_LENGTH, SourceDocument

WIKIVOYAGE_API_URL = "https://en.wikivoyage.org/w/api.php"
WIKIVOYAGE_BASE_PAGE_URL = "https://en.wikivoyage.org/wiki/"
WIKIVOYAGE_LICENSE = "CC BY-SA 4.0 (Wikivoyage contributors)"
WIKIVOYAGE_REQUEST_DELAY_SECONDS = 1.5
MAX_WIKIVOYAGE_DISTRICTS = 8
TOP_SECTION_HEADING_LEVEL = 2
ISO_DATE_PREFIX_LENGTH = 10

WIKIVOYAGE_SECTION_TOPICS = {
    "understand": "overview",
    "districts": "neighborhoods",
    "get in": "getting_in",
    "get around": "getting_around",
    "see": "sightseeing",
    "do": "activities",
    "eat": "food",
    "drink": "food_and_drink",
    "buy": "shopping",
    "respect": "etiquette",
    "stay safe": "safety",
    "cope": "practical_info",
}
WIKIVOYAGE_DISTRICT_ALLOWED_SECTIONS = frozenset(
    {"intro", "get in", "see", "do", "eat", "drink", "stay safe"}
)
WIKIVOYAGE_NOISE_SELECTORS = (
    "style",
    "script",
    "noscript",
    "link",
    "figure",
    ".mw-editsection",
    ".noprint",
    ".toc",
    "#toc",
    ".mw-empty-elt",
    ".magnify",
    ".listing-metadata",
    ".mbox-small",
    ".routeBox",
    ".pagebanner",
    ".geo",
    ".mw-kartographer-container",
    ".mw-kartographer-maplink",
    "table.metadata",
)
HEADING_LEVEL_BY_TAG = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

logger = logging.getLogger("collect_guides")


def clean_inline_text(element: Tag) -> str:
    """Extract readable inline text from an HTML element with normalized punctuation spacing."""
    raw_text = element.get_text(" ", strip=True)
    collapsed = re.sub(r"\s+", " ", raw_text).strip()
    collapsed = re.sub(r"\s+([,.;:!?)\]])", r"\1", collapsed)
    collapsed = re.sub(r"([(\[])\s+", r"\1", collapsed)
    return collapsed


def strip_wikivoyage_noise(root: Tag) -> None:
    """Remove navigation boxes, edit links, maps, and styling from Wikivoyage HTML."""
    for selector in WIKIVOYAGE_NOISE_SELECTORS:
        for unwanted in root.select(selector):
            unwanted.decompose()


def extract_wikivoyage_heading(element: Tag) -> Optional[tuple[int, str]]:
    """Return (level, text) if element is a heading tag or MediaWiki heading wrapper."""
    if element.name in HEADING_LEVEL_BY_TAG:
        heading_text = clean_inline_text(element)
        return (HEADING_LEVEL_BY_TAG[element.name], heading_text) if heading_text else None
    if element.name == "div" and "mw-heading" in (element.get("class") or []):
        inner_heading = element.find(list(HEADING_LEVEL_BY_TAG.keys()))
        if inner_heading is not None:
            heading_text = clean_inline_text(inner_heading)
            level = HEADING_LEVEL_BY_TAG[inner_heading.name]
            return (level, heading_text) if heading_text else None
    return None


def render_list_markdown(list_tag: Tag, indent_level: int = 0) -> list[str]:
    """Convert an HTML <ul> or <ol> element into Markdown bullet or numbered lines."""
    lines: list[str] = []
    ordered = list_tag.name == "ol"
    indent = "  " * indent_level
    item_number = 1
    for child in list_tag.find_all("li", recursive=False):
        nested_lists = child.find_all(["ul", "ol"], recursive=False)
        for nested in nested_lists:
            nested.extract()
        item_text = clean_inline_text(child)
        if item_text:
            prefix = f"{item_number}." if ordered else "-"
            lines.append(f"{indent}{prefix} {item_text}")
            item_number += 1
        for nested in nested_lists:
            lines.extend(render_list_markdown(nested, indent_level=indent_level + 1))
    return lines


def render_table_markdown(table_tag: Tag) -> str:
    """Convert a Wikivoyage region-list or content table into Markdown bullets."""
    if "regionlistitem-table" in (table_tag.get("class") or []):
        entries: list[str] = []
        for cell in table_tag.select("td.regionlistitem-textholder"):
            bold = cell.find("b")
            title_text = clean_inline_text(bold) if bold else ""
            if bold:
                bold.extract()
            description_text = clean_inline_text(cell)
            if title_text and description_text:
                entries.append(f"- **{title_text}**: {description_text}")
            elif title_text or description_text:
                entries.append(f"- {title_text or description_text}")
        return "\n".join(entries)

    rows: list[str] = []
    for row in table_tag.find_all("tr"):
        cells = [clean_inline_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
        non_empty = [cell for cell in cells if cell]
        if non_empty:
            rows.append("- " + " | ".join(non_empty))
    return "\n".join(rows)


def render_wikivoyage_block(element: Tag) -> str:
    """Convert a single top-level HTML block from Wikivoyage into Markdown."""
    heading = extract_wikivoyage_heading(element)
    if heading is not None:
        level, title = heading
        return f"{'#' * level} {title}"
    if element.name == "p":
        return clean_inline_text(element)
    if element.name in ("ul", "ol"):
        return "\n".join(render_list_markdown(element))
    if element.name == "dl":
        entries: list[str] = []
        for child in element.children:
            if not isinstance(child, Tag):
                continue
            text = clean_inline_text(child)
            if not text:
                continue
            if child.name == "dt":
                entries.append(f"**{text}**")
            elif child.name == "dd":
                entries.append(f"- {text}")
        return "\n".join(entries)
    if element.name == "blockquote":
        quote_text = clean_inline_text(element)
        return f"> {quote_text}" if quote_text else ""
    if element.name == "table":
        return render_table_markdown(element)
    if element.name == "div":
        nested_blocks = [
            render_wikivoyage_block(child)
            for child in element.children
            if isinstance(child, Tag)
        ]
        return "\n\n".join(block for block in nested_blocks if block)
    return ""


def split_wikivoyage_sections(parser_output: Tag) -> list[tuple[str, str, list[str]]]:
    """Split a Wikivoyage page body into (section_title, anchor_id, markdown_blocks)."""
    sections: list[tuple[str, str, list[str]]] = []
    current_title = "Intro"
    current_anchor = ""
    current_blocks: list[str] = []

    for child in parser_output.children:
        if not isinstance(child, Tag):
            continue
        heading = extract_wikivoyage_heading(child)
        if heading is not None and heading[0] == TOP_SECTION_HEADING_LEVEL:
            if current_blocks:
                sections.append((current_title, current_anchor, current_blocks))
            current_title = heading[1]
            heading_tag = child.find("h2") if child.name == "div" else child
            current_anchor = (heading_tag.get("id") or "") if heading_tag else ""
            current_blocks = [f"## {current_title}"]
            continue
        rendered = render_wikivoyage_block(child)
        if rendered:
            current_blocks.append(rendered)

    if current_blocks:
        sections.append((current_title, current_anchor, current_blocks))
    return sections


def fetch_wikivoyage_updated_dates(
    session: requests.Session,
    page_titles: list[str],
) -> dict[str, str]:
    """Fetch last-modified YYYY-MM-DD dates for Wikivoyage pages via MediaWiki query API."""
    if not page_titles:
        return {}
    response = fetch_with_retries(
        session,
        WIKIVOYAGE_API_URL,
        params={
            "action": "query",
            "titles": "|".join(page_titles),
            "prop": "revisions",
            "rvprop": "timestamp",
            "format": "json",
        },
    )
    pages = response.json().get("query", {}).get("pages", {})
    updated_dates: dict[str, str] = {}
    for page_info in pages.values():
        title = page_info.get("title")
        revisions = page_info.get("revisions") or []
        if title and revisions and revisions[0].get("timestamp"):
            updated_dates[title] = revisions[0]["timestamp"][:ISO_DATE_PREFIX_LENGTH]
    return updated_dates


def fetch_wikivoyage_parsed_html(session: requests.Session, page_title: str) -> Tag:
    """Fetch parsed HTML body for a Wikivoyage page."""
    response = fetch_with_retries(
        session,
        WIKIVOYAGE_API_URL,
        params={
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json",
        },
    )
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"Wikivoyage API error for '{page_title}': {payload['error']}")
    html_content = payload["parse"]["text"]["*"]
    soup = BeautifulSoup(html_content, "lxml")
    parser_output = soup.select_one("div.mw-parser-output")
    return parser_output if parser_output is not None else soup


def extract_district_subpage_titles(parser_output: Tag, city: str) -> list[str]:
    """Discover linked '<city>/<district>' subpage titles from the main city page."""
    prefix = f"/wiki/{quote(city.replace(' ', '_'))}/"
    discovered: list[str] = []
    seen: set[str] = set()
    for link in parser_output.select("a[href]"):
        href = link.get("href", "")
        if not href.startswith(prefix):
            continue
        raw_page = href.removeprefix("/wiki/").split("#", 1)[0]
        page_title = unquote(raw_page).replace("_", " ").strip()
        if not page_title or page_title in seen or ":" in page_title:
            continue
        seen.add(page_title)
        discovered.append(page_title)
        if len(discovered) >= MAX_WIKIVOYAGE_DISTRICTS:
            break
    return discovered


def wikivoyage_page_url(page_title: str, anchor: str = "") -> str:
    """Build the canonical Wikivoyage URL for a page or section."""
    encoded_title = quote(page_title.replace(" ", "_"), safe="/:")
    base_url = f"{WIKIVOYAGE_BASE_PAGE_URL}{encoded_title}"
    return f"{base_url}#{anchor}" if anchor else base_url


def collect_wikivoyage(
    session: requests.Session,
    city: str,
    retrieved_at: str,
) -> list[SourceDocument]:
    """Collect structured travel guide sections and district pages from Wikivoyage."""
    documents: list[SourceDocument] = []
    main_parser_output = fetch_wikivoyage_parsed_html(session, city)
    district_titles = extract_district_subpage_titles(main_parser_output, city)
    strip_wikivoyage_noise(main_parser_output)

    time.sleep(WIKIVOYAGE_REQUEST_DELAY_SECONDS)
    updated_dates = fetch_wikivoyage_updated_dates(session, [city, *district_titles])
    main_updated_at = updated_dates.get(city, retrieved_at)

    for section_title, anchor, blocks in split_wikivoyage_sections(main_parser_output):
        topic = WIKIVOYAGE_SECTION_TOPICS.get(section_title.lower())
        if topic is None:
            continue
        section_blocks = [
            block for block in blocks if block != f"## {section_title}"
        ]
        body_text = "\n\n".join(section_blocks).strip()
        if len(body_text) < MINIMUM_CONTENT_LENGTH:
            continue
        markdown_body = f"# {city} — {section_title}\n\n{body_text}"
        documents.append(
            SourceDocument(
                document_id=f"{city}_wikivoyage_{section_title}",
                title=f"Wikivoyage {city}: {section_title}",
                city=city,
                topic=topic,
                source_type="official_guide",
                source_url=wikivoyage_page_url(city, anchor=anchor),
                updated_at=main_updated_at,
                retrieved_at=retrieved_at,
                license=WIKIVOYAGE_LICENSE,
                content=markdown_body,
            )
        )

    for district_title in district_titles:
        time.sleep(WIKIVOYAGE_REQUEST_DELAY_SECONDS)
        try:
            district_output = fetch_wikivoyage_parsed_html(session, district_title)
            strip_wikivoyage_noise(district_output)
        except Exception as error:
            logger.warning("Skipping district page '%s': %s", district_title, error)
            continue

        selected_blocks: list[str] = []
        for section_title, _, blocks in split_wikivoyage_sections(district_output):
            if section_title.lower() in WIKIVOYAGE_DISTRICT_ALLOWED_SECTIONS:
                selected_blocks.extend(blocks)

        body_text = "\n\n".join(selected_blocks).strip()
        if len(body_text) < MINIMUM_CONTENT_LENGTH:
            continue

        district_name = district_title.split("/", 1)[-1]
        documents.append(
            SourceDocument(
                document_id=f"{city}_wikivoyage_district_{district_name}",
                title=f"Wikivoyage {city} District Guide: {district_name}",
                city=city,
                topic="neighborhoods",
                source_type="official_guide",
                source_url=wikivoyage_page_url(district_title),
                updated_at=updated_dates.get(district_title, retrieved_at),
                retrieved_at=retrieved_at,
                license=WIKIVOYAGE_LICENSE,
                content=f"# {district_title}\n\n{body_text}",
            )
        )

    return documents
