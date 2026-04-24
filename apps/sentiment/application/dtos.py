"""Sentiment application DTOs."""

from dataclasses import dataclass, field
from datetime import datetime

from apps.sentiment.domain.entities import SentimentAnalysisResult, SentimentIndex


@dataclass(frozen=True)
class SentimentAnalysisResultDTO:
    """Serializable sentiment analysis result."""

    text: str
    sentiment_score: float
    confidence: float
    category: str
    keywords: list[str] = field(default_factory=list)
    analyzed_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def from_domain(cls, result: SentimentAnalysisResult) -> "SentimentAnalysisResultDTO":
        """Build a DTO from a sentiment analysis result."""
        return cls(
            text=result.text,
            sentiment_score=result.sentiment_score,
            confidence=result.confidence,
            category=result.category.value,
            keywords=list(result.keywords),
            analyzed_at=result.analyzed_at,
            error_message=result.error_message,
        )


@dataclass(frozen=True)
class SentimentIndexDTO:
    """Serializable sentiment index."""

    index_date: datetime
    news_sentiment: float
    policy_sentiment: float
    composite_index: float
    confidence_level: float
    data_sufficient: bool

    @classmethod
    def from_domain(cls, index: SentimentIndex) -> "SentimentIndexDTO":
        """Build a DTO from a sentiment index entity."""
        return cls(
            index_date=index.index_date,
            news_sentiment=index.news_sentiment,
            policy_sentiment=index.policy_sentiment,
            composite_index=index.composite_index,
            confidence_level=index.confidence_level,
            data_sufficient=index.data_sufficient,
        )
