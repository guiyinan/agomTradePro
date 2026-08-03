"""Sentiment repository provider for application consumers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Literal, cast

from apps.data_center.application.public import (
    get_news_repository_port,
    get_published_market_news,
)
from apps.data_center.domain.entities import NewsFact
from apps.sentiment.infrastructure.providers import (
    SentimentAlertRepository,
    SentimentAnalysisLogRepository,
    SentimentCacheRepository,
    SentimentConfigRepository,
    SentimentIndexRepository,
)

SentimentNewsReadMode = Literal["published", "historical"]


def _parse_source_datetime(value: object) -> datetime | None:
    """Parse a source timestamp without replacing it with runtime ``now``."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _news_fact_from_payload(payload: Mapping[str, object]) -> NewsFact | None:
    """Convert one Public Port row to the Domain news entity."""

    title = payload.get("title")
    published_at = _parse_source_datetime(payload.get("published_at"))
    fetched_at = _parse_source_datetime(payload.get("fetched_at"))
    if (
        not isinstance(title, str)
        or not title.strip()
        or published_at is None
        or fetched_at is None
    ):
        return None

    def _text(name: str) -> str:
        value = payload.get(name)
        return value if isinstance(value, str) else ""

    raw_sentiment = payload.get("sentiment_score")
    sentiment_score: float | None
    if isinstance(raw_sentiment, bool) or not isinstance(raw_sentiment, (int, float)):
        sentiment_score = None
    else:
        sentiment_score = float(raw_sentiment)

    raw_extra = payload.get("extra")
    extra = dict(raw_extra) if isinstance(raw_extra, Mapping) else {}
    return NewsFact(
        asset_code=_text("asset_code"),
        title=title,
        summary=_text("summary"),
        url=_text("url"),
        published_at=published_at,
        source=_text("source"),
        external_id=_text("external_id"),
        sentiment_score=sentiment_score,
        extra=extra,
        fetched_at=fetched_at,
    )


def _validate_news_read_mode(mode: str) -> SentimentNewsReadMode:
    """Validate the explicit current-vs-historical sentiment read mode."""

    if mode not in {"published", "historical"}:
        raise ValueError("mode must be 'published' or 'historical'")
    return cast(SentimentNewsReadMode, mode)


def get_market_news_for_sentiment(
    target_date: date,
    limit: int = 50,
    *,
    mode: str = "published",
    publication_key: str = "current",
) -> list[NewsFact]:
    """Return sentiment news through the canonical current or historical port.

    ``published`` is the decision-facing default and is bound to the selected
    Data Center Publication members. Historical/as-of calculations must opt
    into ``historical`` explicitly and retain the legacy date-bounded read.
    """

    read_mode = _validate_news_read_mode(mode)
    if read_mode == "historical":
        return get_news_repository_port().list_market_news_for_date(target_date, limit=limit)

    payload = get_published_market_news(
        target_date=target_date,
        limit=limit,
        publication_key=publication_key,
    )
    if bool(payload.get("must_not_use_for_decision")):
        return []
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        return []
    rows: list[NewsFact] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, Mapping):
            news_fact = _news_fact_from_payload(raw_row)
            if news_fact is not None:
                rows.append(news_fact)
    return rows


def get_sentiment_index_repository() -> SentimentIndexRepository:
    """Return the configured sentiment index repository."""

    return SentimentIndexRepository()


def get_sentiment_cache_repository() -> SentimentCacheRepository:
    """Return the configured sentiment cache repository."""

    return SentimentCacheRepository()


def get_sentiment_analysis_log_repository() -> SentimentAnalysisLogRepository:
    """Return the configured sentiment analysis log repository."""

    return SentimentAnalysisLogRepository()


def get_sentiment_alert_repository() -> SentimentAlertRepository:
    """Return the configured sentiment alert repository."""

    return SentimentAlertRepository()


def get_sentiment_config_repository() -> SentimentConfigRepository:
    """Return the configured sentiment config repository."""

    return SentimentConfigRepository()
