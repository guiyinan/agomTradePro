"""Sentiment domain services."""

import math
from datetime import UTC, date, datetime, timedelta

from apps.sentiment.domain.entities import SentimentAnalysisResult
from apps.sentiment.domain.rules import (
    categorize_sentiment_score,
    clamp_sentiment_score,
)


def sentiment_observation_freshness(
    observed_at: date,
    *,
    as_of_date: date,
    max_business_days: int = 1,
) -> tuple[bool, int]:
    """Return stale state and weekday age for a daily sentiment observation."""

    if max_business_days < 0:
        raise ValueError("max_business_days must be non-negative")
    if observed_at > as_of_date:
        return (True, 0)
    current = observed_at + timedelta(days=1)
    age = 0
    while current <= as_of_date:
        if current.weekday() < 5:
            age += 1
        current += timedelta(days=1)
    return (age > max_business_days, age)


def build_sentiment_result(
    *,
    text: str,
    sentiment_score: float,
    confidence: float,
    keywords: list[str] | None = None,
    analyzed_at: datetime | None = None,
    error_message: str | None = None,
) -> SentimentAnalysisResult:
    """Build a normalized sentiment analysis result."""
    normalized_score = clamp_sentiment_score(sentiment_score)
    if isinstance(confidence, bool) or not math.isfinite(confidence):
        raise ValueError("confidence must be a finite number")
    normalized_confidence = max(0.0, min(1.0, confidence))
    return SentimentAnalysisResult(
        text=text,
        sentiment_score=normalized_score,
        confidence=normalized_confidence,
        category=categorize_sentiment_score(normalized_score),
        keywords=keywords or [],
        analyzed_at=analyzed_at or datetime.now(UTC),
        error_message=error_message,
    )
