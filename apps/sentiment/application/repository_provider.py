"""Sentiment repository provider for application consumers."""

from __future__ import annotations

from datetime import date

from apps.data_center.application.public import (
    get_current_publication,
    get_news_repository_port,
)
from apps.data_center.domain.entities import NewsFact
from apps.sentiment.infrastructure.providers import (
    SentimentAlertRepository,
    SentimentAnalysisLogRepository,
    SentimentCacheRepository,
    SentimentConfigRepository,
    SentimentIndexRepository,
)


def get_market_news_for_sentiment(
    target_date: date,
    limit: int = 50,
) -> list[NewsFact]:
    """Return market-wide news for sentiment calculation via data_center."""

    # Sentiment is a decision-facing aggregation.  A non-empty canonical fact
    # is not sufficient without an active market.news Publication; fail closed
    # rather than silently scoring an unpublished/stale snapshot.
    if get_current_publication("market.news", "current") is None:
        return []
    return get_news_repository_port().list_market_news_for_date(target_date, limit=limit)


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
