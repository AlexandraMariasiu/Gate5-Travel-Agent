"""Reddit community_forum collector supporting OAuth API and Arctic Shift fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import logging
import os
import re
import time
from typing import Any, Optional

import requests

from scripts.collectors.http_client import (
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    fetch_with_retries,
)
from scripts.collectors.models import MINIMUM_CONTENT_LENGTH, SourceDocument

REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_API_URL = "https://oauth.reddit.com"
ARCTIC_SHIFT_POSTS_IDS_URL = "https://arctic-shift.photon-reddit.com/api/posts/ids"
ARCTIC_SHIFT_POSTS_SEARCH_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_SHIFT_COMMENTS_URL = "https://arctic-shift.photon-reddit.com/api/comments/search"

REDDIT_CLIENT_ID_ENV = "REDDIT_CLIENT_ID"
REDDIT_CLIENT_SECRET_ENV = "REDDIT_CLIENT_SECRET"

REDDIT_REQUEST_DELAY_SECONDS = 2.5
ARCTIC_SHIFT_COMMENT_FETCH_LIMIT = 50
ARCTIC_SHIFT_SEARCH_LIMIT = 25
OAUTH_SEARCH_LIMIT = 10
OAUTH_COMMENTS_LIMIT = 30
MAX_COMMENTS_PER_THREAD = 12
MINIMUM_COMMENT_LENGTH = 30
MINIMUM_COMMENT_SCORE = 1
OAUTH_COMMENTS_INDEX = 1
MINIMUM_OAUTH_THREAD_PARTS = 2

DELETED_MARKERS = frozenset({"[deleted]", "[removed]", ""})
EXCLUDED_AUTHORS = frozenset({"AutoModerator", "[deleted]"})

REDDIT_OAUTH_QUERIES: tuple[tuple[str, str, str], ...] = (
    ("ItalyTravel", "{city} tips", "practical_tips"),
    ("ItalyTravel", "{city} scams", "safety"),
    ("ItalyTravel", "{city} rain", "rainy_day"),
    ("ItalyTravel", "{city} public transport", "getting_around"),
    ("ItalyTravel", "{city} food", "food"),
    ("ItalyTravel", "{city} neighborhoods", "neighborhoods"),
    ("rome", "tips", "practical_tips"),
    ("rome", "scams", "safety"),
    ("rome", "rain", "rainy_day"),
    ("rome", "metro bus", "getting_around"),
)


@dataclass(frozen=True)
class RedditSeedThread:
    """Curated high-signal Reddit thread identifier and assigned topic."""

    post_id: str
    topic: str


CURATED_REDDIT_SEEDS_BY_CITY: dict[str, tuple[RedditSeedThread, ...]] = {
    "rome": (
        RedditSeedThread(post_id="1m4ebz5", topic="safety"),
        RedditSeedThread(post_id="1o1s89g", topic="safety"),
        RedditSeedThread(post_id="1g9s0g5", topic="safety"),
        RedditSeedThread(post_id="177389e", topic="rainy_day"),
        RedditSeedThread(post_id="1sld0o3", topic="getting_around"),
        RedditSeedThread(post_id="1rvb3v0", topic="food"),
        RedditSeedThread(post_id="1thlxqn", topic="practical_tips"),
        RedditSeedThread(post_id="1peqb3d", topic="itinerary_tips"),
    ),
}

logger = logging.getLogger("collect_guides")


def format_utc_date(timestamp_seconds: Optional[float], fallback_date: str) -> str:
    """Convert a Unix timestamp in seconds into YYYY-MM-DD format."""
    if not timestamp_seconds:
        return fallback_date
    return datetime.fromtimestamp(float(timestamp_seconds), tz=timezone.utc).strftime("%Y-%m-%d")


def clean_reddit_text(raw_text: str) -> str:
    """Decode HTML entities and normalize excessive blank lines in Reddit Markdown."""
    unescaped = html.unescape(raw_text or "").strip()
    unescaped = unescaped.replace("\r\n", "\n")
    return re.sub(r"\n{3,}", "\n\n", unescaped)


def filter_and_rank_comments(
    comment_records: list[dict[str, Any]],
    post_id: str,
) -> list[dict[str, Any]]:
    """Select clean, high-scoring comments, prioritizing top-level replies."""
    post_fullname = f"t3_{post_id}"
    valid_comments: list[dict[str, Any]] = []
    seen_bodies: set[str] = set()
    for comment in comment_records:
        author = str(comment.get("author") or "")
        body = clean_reddit_text(str(comment.get("body") or ""))
        score = int(comment.get("score") or 0)
        if author in EXCLUDED_AUTHORS or body in DELETED_MARKERS:
            continue
        if len(body) < MINIMUM_COMMENT_LENGTH or score < MINIMUM_COMMENT_SCORE:
            continue
        normalized_body = body.lower()
        if normalized_body in seen_bodies:
            continue
        seen_bodies.add(normalized_body)
        is_top_level = str(comment.get("parent_id") or "") == post_fullname
        valid_comments.append(
            {
                "body": body,
                "score": score,
                "is_top_level": is_top_level,
            }
        )

    valid_comments.sort(
        key=lambda item: (item["is_top_level"], item["score"]),
        reverse=True,
    )
    return valid_comments[:MAX_COMMENTS_PER_THREAD]


def build_thread_document(
    post_data: dict[str, Any],
    comment_records: list[dict[str, Any]],
    *,
    city: str,
    topic: str,
    retrieved_at: str,
) -> Optional[SourceDocument]:
    """Build a normalized SourceDocument from a Reddit post and its top comments."""
    post_id = str(post_data.get("id") or "").strip()
    title = clean_reddit_text(str(post_data.get("title") or ""))
    subreddit_name = str(post_data.get("subreddit") or "").strip()
    permalink = str(post_data.get("permalink") or "").strip()
    selftext = clean_reddit_text(str(post_data.get("selftext") or ""))
    post_score = int(post_data.get("score") or 0)
    comment_count = int(post_data.get("num_comments") or len(comment_records))

    if not post_id or not title or not subreddit_name or not permalink:
        return None
    if selftext in {"[deleted]", "[removed]"}:
        return None

    created_date = format_utc_date(post_data.get("created_utc"), retrieved_at)
    selected_comments = filter_and_rank_comments(comment_records, post_id)
    if not selftext and not selected_comments:
        return None

    sections: list[str] = [
        f"# {title}",
        (
            f"**Subreddit:** r/{subreddit_name} | **Score:** {post_score} | "
            f"**Comments:** {comment_count} | **Posted:** {created_date}"
        ),
    ]
    if selftext:
        sections.append(f"## Original Post\n\n{selftext}")
    if selected_comments:
        comment_blocks = [
            f"### Comment {index} (score: {comment['score']})\n\n{comment['body']}"
            for index, comment in enumerate(selected_comments, start=1)
        ]
        sections.append("## Top Community Responses\n\n" + "\n\n".join(comment_blocks))

    full_content = "\n\n".join(sections)
    if len(full_content.strip()) < MINIMUM_CONTENT_LENGTH:
        return None

    return SourceDocument(
        document_id=f"{city}_reddit_{subreddit_name}_{post_id}",
        title=f"Reddit r/{subreddit_name}: {title}",
        city=city,
        topic=topic,
        source_type="community_forum",
        source_url=f"{REDDIT_BASE_URL}{permalink}",
        updated_at=created_date,
        retrieved_at=retrieved_at,
        license=f"Reddit public thread (r/{subreddit_name}); attributed for academic RAG",
        content=full_content,
    )


def fetch_reddit_oauth_token(
    session: requests.Session,
    client_id: str,
    client_secret: str,
) -> str:
    """Obtain an application-only OAuth bearer token from Reddit."""
    response = session.post(
        REDDIT_OAUTH_TOKEN_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Reddit OAuth token response did not include access_token.")
    return str(token)


def collect_via_reddit_oauth(
    session: requests.Session,
    city: str,
    retrieved_at: str,
    *,
    client_id: str,
    client_secret: str,
    minimum_score: int,
) -> list[SourceDocument]:
    """Collect top-voted Reddit threads directly via oauth.reddit.com."""
    token = fetch_reddit_oauth_token(session, client_id, client_secret)
    oauth_headers = {
        "Authorization": f"bearer {token}",
        "User-Agent": USER_AGENT,
    }

    seen_post_ids: set[str] = set()
    documents: list[SourceDocument] = []
    city_lower = city.lower()

    for subreddit_name, query_template, topic in REDDIT_OAUTH_QUERIES:
        if subreddit_name.lower() == "rome" and city_lower != "rome":
            continue
        query_text = query_template.format(city=city)
        time.sleep(REDDIT_REQUEST_DELAY_SECONDS)
        search_response = session.get(
            f"{REDDIT_OAUTH_API_URL}/r/{subreddit_name}/search",
            params={
                "q": query_text,
                "restrict_sr": "1",
                "sort": "top",
                "t": "all",
                "limit": OAUTH_SEARCH_LIMIT,
            },
            headers=oauth_headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        search_response.raise_for_status()
        children = search_response.json().get("data", {}).get("children", [])

        for child in children:
            post_data = child.get("data", {})
            post_id = str(post_data.get("id") or "")
            post_score = int(post_data.get("score") or 0)
            title_lower = str(post_data.get("title") or "").lower()
            if not post_id or post_id in seen_post_ids or post_score < minimum_score:
                continue
            if subreddit_name.lower() != city_lower and city_lower not in title_lower:
                continue
            seen_post_ids.add(post_id)

            time.sleep(REDDIT_REQUEST_DELAY_SECONDS)
            thread_response = session.get(
                f"{REDDIT_OAUTH_API_URL}/comments/{post_id}",
                params={"sort": "top", "limit": OAUTH_COMMENTS_LIMIT},
                headers=oauth_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            thread_response.raise_for_status()
            payload = thread_response.json()
            comment_children = (
                payload[OAUTH_COMMENTS_INDEX].get("data", {}).get("children", [])
                if isinstance(payload, list) and len(payload) >= MINIMUM_OAUTH_THREAD_PARTS
                else []
            )
            comment_records = [
                item.get("data", {})
                for item in comment_children
                if item.get("kind") == "t1"
            ]
            document = build_thread_document(
                post_data,
                comment_records,
                city=city,
                topic=topic,
                retrieved_at=retrieved_at,
            )
            if document is not None:
                documents.append(document)

    return documents


def fetch_arctic_shift_comments(
    session: requests.Session,
    post_id: str,
) -> list[dict[str, Any]]:
    """Fetch archived comments for a Reddit post from Arctic Shift."""
    response = fetch_with_retries(
        session,
        ARCTIC_SHIFT_COMMENTS_URL,
        params={
            "link_id": post_id,
            "limit": ARCTIC_SHIFT_COMMENT_FETCH_LIMIT,
        },
    )
    return response.json().get("data") or []


def collect_via_arctic_shift(
    session: requests.Session,
    city: str,
    retrieved_at: str,
    *,
    minimum_score: int,
) -> list[SourceDocument]:
    """Collect Reddit threads and comments from the Arctic Shift public archive."""
    seeds = CURATED_REDDIT_SEEDS_BY_CITY.get(city.lower(), ())
    documents: list[SourceDocument] = []

    if seeds:
        topic_by_post_id = {seed.post_id: seed.topic for seed in seeds}
        posts_response = fetch_with_retries(
            session,
            ARCTIC_SHIFT_POSTS_IDS_URL,
            params={"ids": ",".join(topic_by_post_id.keys())},
        )
        posts = posts_response.json().get("data") or []
        for post_data in posts:
            post_id = str(post_data.get("id") or "")
            post_score = int(post_data.get("score") or 0)
            if post_score < minimum_score:
                logger.info(
                    "Skipping Reddit post %s (score %d < minimum %d)",
                    post_id,
                    post_score,
                    minimum_score,
                )
                continue
            time.sleep(REDDIT_REQUEST_DELAY_SECONDS)
            try:
                comment_records = fetch_arctic_shift_comments(session, post_id)
            except Exception as error:
                logger.warning("Failed fetching comments for post %s: %s", post_id, error)
                comment_records = []

            document = build_thread_document(
                post_data,
                comment_records,
                city=city,
                topic=topic_by_post_id.get(post_id, "practical_tips"),
                retrieved_at=retrieved_at,
            )
            if document is not None:
                documents.append(document)
        return documents

    search_response = fetch_with_retries(
        session,
        ARCTIC_SHIFT_POSTS_SEARCH_URL,
        params={
            "subreddit": "ItalyTravel",
            "query": city,
            "limit": ARCTIC_SHIFT_SEARCH_LIMIT,
            "sort": "desc",
        },
    )
    posts = search_response.json().get("data") or []
    city_lower = city.lower()
    for post_data in posts:
        post_id = str(post_data.get("id") or "")
        post_score = int(post_data.get("score") or 0)
        title_lower = str(post_data.get("title") or "").lower()
        if post_score < minimum_score or city_lower not in title_lower:
            continue
        time.sleep(REDDIT_REQUEST_DELAY_SECONDS)
        comment_records = fetch_arctic_shift_comments(session, post_id)
        document = build_thread_document(
            post_data,
            comment_records,
            city=city,
            topic="practical_tips",
            retrieved_at=retrieved_at,
        )
        if document is not None:
            documents.append(document)
    return documents


def collect_reddit(
    session: requests.Session,
    city: str,
    retrieved_at: str,
    *,
    minimum_score: int,
) -> list[SourceDocument]:
    """Collect Reddit discussions via OAuth if configured, else Arctic Shift archive."""
    client_id = os.environ.get(REDDIT_CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(REDDIT_CLIENT_SECRET_ENV, "").strip()
    if client_id and client_secret:
        logger.info("Using official Reddit OAuth API (oauth.reddit.com).")
        return collect_via_reddit_oauth(
            session,
            city,
            retrieved_at,
            client_id=client_id,
            client_secret=client_secret,
            minimum_score=minimum_score,
        )

    logger.info(
        "Reddit OAuth credentials not set; falling back to Arctic Shift public archive API."
    )
    return collect_via_arctic_shift(
        session,
        city,
        retrieved_at,
        minimum_score=minimum_score,
    )
