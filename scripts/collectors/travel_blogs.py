"""Travel blog and editorial web article collector using trafilatura and BeautifulSoup."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import time
from typing import Optional

from bs4 import BeautifulSoup
import requests
import trafilatura

from scripts.collectors.http_client import fetch_with_retries
from scripts.collectors.models import MINIMUM_CONTENT_LENGTH, SourceDocument

BLOG_REQUEST_DELAY_SECONDS = 1.0
ISO_DATE_PREFIX_LENGTH = 10
MIN_EXTRACTED_HEADING_LENGTH = 3
BLOG_LICENSE_TEMPLATE = "Editorial web article ({source_name}); attributed for academic RAG"

HTML_BOILERPLATE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
    ".related-post",
    ".related-posts",
    ".yarpp-related",
    ".affiliate-disclosure",
    ".TopResourcesBlock",
    ".sharedaddy",
    "[class*='newsletter']",
    "[class*='cookie']",
    "[class*='sidebar']",
    "[class*='social-share']",
)

MODIFIED_TIME_META_SELECTORS = (
    "meta[property='article:modified_time']",
    "meta[property='og:updated_time']",
    "meta[name='lastmod']",
    "meta[property='article:published_time']",
)

FALLBACK_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "p", "li")
HEADING_PREFIX_BY_TAG = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}

logger = logging.getLogger("collect_guides")


@dataclass(frozen=True)
class TravelBlogSource:
    """Configuration for a curated travel blog article."""

    document_id: str
    topic: str
    url: str
    source_name: str
    fallback_title: str


CURATED_BLOG_SOURCES_BY_CITY: dict[str, tuple[TravelBlogSource, ...]] = {
    "rome": (
        TravelBlogSource(
            document_id="rome_blog_ricksteves_itinerary",
            topic="itinerary_tips",
            url="https://www.ricksteves.com/europe/italy/rome-itinerary",
            source_name="Rick Steves' Europe",
            fallback_title="Rome Itinerary: Planning Your Time",
        ),
        TravelBlogSource(
            document_id="rome_blog_romewise_rainy_day",
            topic="rainy_day",
            url="https://romewise.com/essential-things/weather/how-to-have-fun-in-rome-on-a-rainy-day/",
            source_name="Romewise",
            fallback_title="How to Have Fun in Rome on a Rainy Day",
        ),
        TravelBlogSource(
            document_id="rome_blog_fhtr_rainy_day",
            topic="rainy_day",
            url="https://www.fromhometorome.com/what-to-do-in-rome-on-a-rainy-day/",
            source_name="From Home to Rome",
            fallback_title="What to Do in Rome on a Rainy Day",
        ),
        TravelBlogSource(
            document_id="rome_blog_fhtr_neighborhoods",
            topic="neighborhoods",
            url="https://www.fromhometorome.com/choosing-the-best-neighborhood-for-your-vacation-in-rome/",
            source_name="From Home to Rome",
            fallback_title="Choosing the Best Neighborhood for Your Vacation in Rome",
        ),
        TravelBlogSource(
            document_id="rome_blog_fhtr_trastevere",
            topic="neighborhoods",
            url="https://www.fromhometorome.com/a-day-in-trastevere-what-to-do-where-to-eat-and-how-not-to-waste-it/",
            source_name="From Home to Rome",
            fallback_title="A Day in Trastevere: What to Do, Where to Eat, and How Not to Waste It",
        ),
        TravelBlogSource(
            document_id="rome_blog_romewise_food_customs",
            topic="food",
            url="https://romewise.com/food-drink-in-rome/my-complete-guide-to-understanding-italian-food-customs/",
            source_name="Romewise",
            fallback_title="Understanding Italian Food Customs in Rome",
        ),
        TravelBlogSource(
            document_id="rome_blog_romewise_transport",
            topic="getting_around",
            url="https://romewise.com/essential-things/transport/rome-transportation-how-to-explore-the-eternal-city/",
            source_name="Romewise",
            fallback_title="Rome Transportation: How to Explore the Eternal City",
        ),
        TravelBlogSource(
            document_id="rome_blog_fhtr_tourist_scams",
            topic="safety",
            url="https://www.fromhometorome.com/stay-safe-in-rome-unmasking-the-top-tourist-scams/",
            source_name="From Home to Rome",
            fallback_title="Stay Safe in Rome: Unmasking the Top Tourist Scams",
        ),
    ),
}


def strip_html_boilerplate(raw_html: str) -> tuple[str, Optional[str]]:
    """Remove common navigation, ad, and widget boilerplate and read modified date."""
    soup = BeautifulSoup(raw_html, "lxml")

    modified_date: Optional[str] = None
    for selector in MODIFIED_TIME_META_SELECTORS:
        meta_tag = soup.select_one(selector)
        content_value = (meta_tag.get("content") or "").strip() if meta_tag else ""
        if re.match(r"^\d{4}-\d{2}-\d{2}", content_value):
            modified_date = content_value[:ISO_DATE_PREFIX_LENGTH]
            break

    for selector in HTML_BOILERPLATE_SELECTORS:
        for unwanted in soup.select(selector):
            unwanted.decompose()

    return str(soup), modified_date


def extract_markdown_fallback(cleaned_html: str) -> str:
    """Fallback BeautifulSoup extractor when trafilatura returns insufficient text."""
    soup = BeautifulSoup(cleaned_html, "lxml")
    container = soup.find("article") or soup.find("main") or soup.body or soup
    blocks: list[str] = []
    for element in container.find_all(FALLBACK_BLOCK_TAGS):
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) < MIN_EXTRACTED_HEADING_LENGTH:
            continue
        if element.name in HEADING_PREFIX_BY_TAG:
            blocks.append(f"{HEADING_PREFIX_BY_TAG[element.name]} {text}")
        elif element.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)


def clean_extracted_markdown(markdown_text: str, title: str) -> str:
    """Normalize whitespace, strip date/newsletter widgets, and ensure an H1 title."""
    cleaned = markdown_text.strip()
    cleaned = re.sub(
        r"^(?:#{1,6}\s+(?:Last updated|Published)\s+on:\s*\n+[^\n]+\n*)+",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    cleaned = re.sub(
        r"\n+[^\n]*subscribe to our[^\n]*newsletter[^\n]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned.strip())
    if not cleaned.startswith("# "):
        cleaned = f"# {title}\n\n{cleaned}"
    return cleaned


def extract_blog_article(
    raw_html: str,
    source: TravelBlogSource,
    retrieved_at: str,
) -> tuple[str, str, str]:
    """Extract (title, updated_at, markdown_body) from raw article HTML."""
    cleaned_html, meta_modified_date = strip_html_boilerplate(raw_html)
    metadata = trafilatura.extract_metadata(cleaned_html, default_url=source.url)

    title = (metadata.title.strip() if metadata and metadata.title else "") or source.fallback_title
    updated_at = meta_modified_date or (
        metadata.date[:ISO_DATE_PREFIX_LENGTH]
        if metadata and metadata.date and re.match(r"^\d{4}-\d{2}-\d{2}", metadata.date)
        else retrieved_at
    )

    extracted = trafilatura.extract(
        cleaned_html,
        url=source.url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=False,
        deduplicate=True,
    )
    if not extracted or len(extracted.strip()) < MINIMUM_CONTENT_LENGTH:
        extracted = extract_markdown_fallback(cleaned_html)

    markdown_body = clean_extracted_markdown(extracted or "", title)
    return title, updated_at, markdown_body


def collect_travel_blogs(
    session: requests.Session,
    city: str,
    retrieved_at: str,
) -> list[SourceDocument]:
    """Collect and clean curated travel blog articles for the target city."""
    sources = CURATED_BLOG_SOURCES_BY_CITY.get(city.lower(), ())
    if not sources:
        logger.info("No curated travel blog URLs configured for city '%s'.", city)
        return []

    documents: list[SourceDocument] = []
    for index, source in enumerate(sources):
        if index > 0:
            time.sleep(BLOG_REQUEST_DELAY_SECONDS)
        try:
            response = fetch_with_retries(session, source.url)
            title, updated_at, markdown_body = extract_blog_article(
                response.text,
                source,
                retrieved_at,
            )
            documents.append(
                SourceDocument(
                    document_id=source.document_id,
                    title=title,
                    city=city,
                    topic=source.topic,
                    source_type="travel_blog",
                    source_url=response.url,
                    updated_at=updated_at,
                    retrieved_at=retrieved_at,
                    license=BLOG_LICENSE_TEMPLATE.format(source_name=source.source_name),
                    content=markdown_body,
                )
            )
        except Exception as error:
            logger.warning("Skipping travel blog '%s': %s", source.url, error)

    return documents
