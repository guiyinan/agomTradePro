"""Canonical freshness-aware resolver for the latest sentiment index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.sentiment.application import repository_provider
from apps.sentiment.domain.entities import SentimentIndex
from apps.sentiment.domain.services import sentiment_observation_freshness


@dataclass(frozen=True)
class CurrentSentimentResult:
    """Decision-safe sentiment index plus diagnostic provenance."""

    index: SentimentIndex | None
    diagnostic_index: SentimentIndex | None
    observed_at: date | None
    freshness_status: str
    staleness_days: int | None
    must_not_use_for_decision: bool
    blocked_reason: str


def get_sentiment_index_repository() -> Any:
    """Resolve the repository at call time for injectable test boundaries."""

    return repository_provider.get_sentiment_index_repository()


def resolve_current_sentiment(
    *,
    as_of_date: date | None = None,
    max_business_days: int = 1,
) -> CurrentSentimentResult:
    """Return the latest sentiment only when fresh and data-sufficient."""

    target_date = as_of_date or date.today()
    latest = get_sentiment_index_repository().get_latest()
    if latest is None:
        return CurrentSentimentResult(
            index=None,
            diagnostic_index=None,
            observed_at=None,
            freshness_status="missing",
            staleness_days=None,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_index_missing",
        )

    observed_at = latest.index_date.date()
    is_stale, staleness_days = sentiment_observation_freshness(
        observed_at,
        as_of_date=target_date,
        max_business_days=max_business_days,
    )
    if is_stale:
        return CurrentSentimentResult(
            index=None,
            diagnostic_index=latest,
            observed_at=observed_at,
            freshness_status="stale",
            staleness_days=staleness_days,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_index_stale",
        )
    if not latest.data_sufficient:
        return CurrentSentimentResult(
            index=None,
            diagnostic_index=latest,
            observed_at=observed_at,
            freshness_status="insufficient",
            staleness_days=staleness_days,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_data_insufficient",
        )
    return CurrentSentimentResult(
        index=latest,
        diagnostic_index=latest,
        observed_at=observed_at,
        freshness_status="fresh",
        staleness_days=staleness_days,
        must_not_use_for_decision=False,
        blocked_reason="",
    )
