"""Sentiment repository provider for application consumers."""

from __future__ import annotations

from apps.sentiment.infrastructure.providers import (
    SentimentAlertRepository,
    SentimentAnalysisLogRepository,
    SentimentCacheRepository,
    SentimentConfigRepository,
    SentimentIndexRepository,
)


def get_market_news_for_sentiment(target_date, limit: int = 50):
    """Return market-wide news for sentiment calculation via data_center."""

    from apps.data_center.application.repository_provider import get_news_repository

    return get_news_repository().list_market_news_for_date(target_date, limit=limit)


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
