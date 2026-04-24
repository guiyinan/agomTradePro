"""Sentiment domain rules."""

from apps.sentiment.domain.entities import SentimentCategory


def categorize_sentiment_score(score: float) -> SentimentCategory:
    """Map a numeric sentiment score to a sentiment category."""
    if score > 0.5:
        return SentimentCategory.POSITIVE
    if score < -0.5:
        return SentimentCategory.NEGATIVE
    return SentimentCategory.NEUTRAL


def clamp_sentiment_score(score: float) -> float:
    """Clamp a sentiment score to the domain range."""
    return max(-3.0, min(3.0, score))
