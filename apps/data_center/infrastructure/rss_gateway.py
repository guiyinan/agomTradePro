"""Controlled RSS transport for Data Center news ingestion.

The Policy app owns classification and review workflow, but it must not own
network access to an external news feed.  This gateway keeps HTTP, retry, and
feedparser concerns inside Data Center and returns canonical-domain news
facts with source observation time preserved.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from importlib import import_module
from time import sleep, struct_time
from typing import Protocol, cast
from urllib.parse import urlsplit

import requests

from apps.data_center.domain.entities import NewsFact

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "AgomTradePro-RSS-Bot/1.0"


class RSSGatewayError(RuntimeError):
    """Raised when a bounded RSS fetch cannot produce a usable response."""


class RSSFeedEntryProtocol(Protocol):
    """Minimal feedparser entry surface consumed by the gateway."""

    published_parsed: struct_time | None
    updated_parsed: struct_time | None

    def get(self, key: str, default: str = "") -> object:
        """Return one optional parsed feed field."""


class RSSParsedFeedProtocol(Protocol):
    """Minimal feedparser result surface consumed by the gateway."""

    bozo: bool
    bozo_exception: BaseException | None
    entries: list[RSSFeedEntryProtocol]


def fetch_rss_feed(
    *,
    url: str,
    source_name: str,
    timeout_seconds: int = 30,
    retry_times: int = 3,
    proxy_config: Mapping[str, str] | None = None,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> list[NewsFact]:
    """Fetch one RSS feed and return validated canonical news facts.

    Missing or malformed source publication timestamps are rejected instead
    of being replaced with request time.  The returned ``fetched_at`` records
    the transport observation time for every item in this response.
    """

    _validate_request(url, source_name, timeout_seconds, retry_times)
    content = _fetch_bytes(
        url=url,
        timeout_seconds=timeout_seconds,
        retry_times=retry_times,
        proxy_config=proxy_config,
        user_agent=user_agent,
    )
    parser = import_module("feedparser")
    feed = cast(RSSParsedFeedProtocol, parser.parse(content))
    if feed.bozo and feed.bozo_exception:
        logger.warning(
            "rss_parse_warning source=%s error_type=%s",
            source_name,
            type(feed.bozo_exception).__name__,
        )

    fetched_at = datetime.now(UTC)
    items: list[NewsFact] = []
    for entry in getattr(feed, "entries", []):
        item = _to_news_fact(entry, source_name=source_name, fetched_at=fetched_at)
        if item is not None:
            items.append(item)
    return items


def probe_rss_feed(
    *,
    url: str,
    source_name: str,
    timeout_seconds: int = 30,
    retry_times: int = 1,
    proxy_config: Mapping[str, str] | None = None,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> None:
    """Probe one RSS source without parsing or persisting its response."""

    _validate_request(url, source_name, timeout_seconds, retry_times)
    _fetch_bytes(
        url=url,
        timeout_seconds=timeout_seconds,
        retry_times=retry_times,
        proxy_config=proxy_config,
        user_agent=user_agent,
    )


def _validate_request(
    url: str,
    source_name: str,
    timeout_seconds: int,
    retry_times: int,
) -> None:
    if not source_name.strip():
        raise ValueError("RSS source_name cannot be empty")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("RSS URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("RSS URL must not contain credentials")
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 120:
        raise ValueError("RSS timeout_seconds must be between 1 and 120")
    if isinstance(retry_times, bool) or not 1 <= retry_times <= 10:
        raise ValueError("RSS retry_times must be between 1 and 10")


def _fetch_bytes(
    *,
    url: str,
    timeout_seconds: int,
    retry_times: int,
    proxy_config: Mapping[str, str] | None,
    user_agent: str,
) -> bytes:
    last_error: Exception | None = None
    headers = {"User-Agent": user_agent.strip() or _DEFAULT_USER_AGENT}
    for attempt in range(1, retry_times + 1):
        try:
            response = requests.get(
                url,
                proxies=dict(proxy_config) if proxy_config is not None else None,
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.content
        except requests.Timeout as exc:
            last_error = exc
            logger.warning("rss_fetch_timeout attempt=%s/%s", attempt, retry_times)
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("rss_fetch_error attempt=%s/%s", attempt, retry_times)
        if attempt < retry_times:
            sleep(min(attempt * 2, 10))
    raise RSSGatewayError(f"RSS fetch failed after {retry_times} retries") from last_error


def _to_news_fact(
    entry: RSSFeedEntryProtocol,
    *,
    source_name: str,
    fetched_at: datetime,
) -> NewsFact | None:
    title = str(entry.get("title", "") or "").strip()
    link = str(entry.get("link", "") or "").strip()
    if not title or not link:
        return None
    published_at = _parse_source_datetime(entry)
    if published_at is None:
        logger.warning("rss_item_missing_observed_time source=%s", source_name)
        return None
    description = str(entry.get("description", "") or entry.get("summary", "") or "")
    guid = str(entry.get("guid", "") or "").strip()
    author = str(entry.get("author", "") or "").strip()
    return NewsFact(
        asset_code="",
        title=title,
        published_at=published_at,
        source=source_name,
        summary=description,
        url=link,
        external_id=guid,
        extra={"author": author} if author else {},
        fetched_at=fetched_at,
    )


def _parse_source_datetime(entry: RSSFeedEntryProtocol) -> datetime | None:
    for parsed in (entry.published_parsed, entry.updated_parsed):
        if parsed is not None:
            try:
                return datetime(*parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    for key in ("published", "pubDate", "updated"):
        raw = str(entry.get(key, "") or "").strip()
        if not raw:
            continue
        try:
            parsed_datetime = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=UTC)
        return parsed_datetime.astimezone(UTC)
    return None


__all__ = ["RSSGatewayError", "fetch_rss_feed", "probe_rss_feed"]
