"""Sentiment domain rules."""

import math

from apps.sentiment.domain.entities import SentimentCategory


def require_finite_sentiment_value(
    value: float,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    """Return a finite sentiment value inside the requested inclusive range."""

    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def categorize_sentiment_score(score: float) -> SentimentCategory:
    """Map a numeric sentiment score to a sentiment category."""
    require_finite_sentiment_value(
        score,
        name="score",
        minimum=-3.0,
        maximum=3.0,
    )
    if score > 0.5:
        return SentimentCategory.POSITIVE
    if score < -0.5:
        return SentimentCategory.NEGATIVE
    return SentimentCategory.NEUTRAL


def clamp_sentiment_score(score: float) -> float:
    """Clamp a sentiment score to the domain range."""
    if isinstance(score, bool) or not math.isfinite(score):
        raise ValueError("score must be a finite number")
    return max(-3.0, min(3.0, score))
