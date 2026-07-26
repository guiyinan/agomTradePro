"""Sentiment domain services."""

import math
from datetime import UTC, datetime

from apps.sentiment.domain.entities import SentimentAnalysisResult
from apps.sentiment.domain.rules import (
    categorize_sentiment_score,
    clamp_sentiment_score,
)


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
