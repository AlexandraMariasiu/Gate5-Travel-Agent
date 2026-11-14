"""HTTP session and retry helpers for polite source fetching."""

from __future__ import annotations

from http import HTTPStatus
import logging
import time
from typing import Optional

import requests

USER_AGENT = (
    "Gate5TravelAgent/0.1 (https://github.com/Gate5-Travel-Agent; "
    "academic travel research) python-requests"
)
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

logger = logging.getLogger("collect_guides")


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
    """Fetch a URL with retry/backoff handling and Retry-After support."""
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout_seconds)
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = requests.HTTPError(
                    f"HTTP {response.status_code} for {url}", response=response
                )
                retry_after_header = response.headers.get("Retry-After", "")
                if retry_after_header.isdigit():
                    wait_seconds = max(float(retry_after_header), backoff_seconds)
                else:
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
