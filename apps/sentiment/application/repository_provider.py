"""Sentiment repository provider for application consumers."""

from __future__ import annotations

from apps.sentiment.infrastructure.providers import SentimentIndexRepository


def get_sentiment_index_repository() -> SentimentIndexRepository:
    """Return the configured sentiment index repository."""

    return SentimentIndexRepository()
