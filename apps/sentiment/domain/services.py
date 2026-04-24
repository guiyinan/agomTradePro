"""Sentiment domain services."""

from datetime import datetime, timezone

from apps.sentiment.domain.entities import SentimentAnalysisResult
from apps.sentiment.domain.rules import categorize_sentiment_score, clamp_sentiment_score


def build_sentiment_result(
    *,
    text: str,
    sentiment_score: float,
    confidence: float,
    keywords: list[str] | None = None,
    analyzed_at=None,
    error_message: str | None = None,
) -> SentimentAnalysisResult:
    """Build a normalized sentiment analysis result."""
    normalized_score = clamp_sentiment_score(sentiment_score)
    return SentimentAnalysisResult(
        text=text,
        sentiment_score=normalized_score,
        confidence=max(0.0, min(1.0, confidence)),
        category=categorize_sentiment_score(normalized_score),
        keywords=keywords or [],
        analyzed_at=analyzed_at or datetime.now(timezone.utc),
        error_message=error_message,
    )
