"""Decision-safe sentiment observations exposed to the Pulse application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.sentiment.application.repository_provider import get_sentiment_index_repository
from apps.sentiment.domain.services import sentiment_observation_freshness


@dataclass(frozen=True)
class SentimentPulsePoint:
    """One date-labelled composite sentiment observation."""

    observed_at: date
    value: float


@dataclass(frozen=True)
class SentimentPulseSeriesResult:
    """Fresh series or an explicit fail-closed decision block."""

    points: tuple[SentimentPulsePoint, ...]
    observed_at: date | None
    must_not_use_for_decision: bool
    blocked_reason: str


def get_sentiment_pulse_series(
    *,
    as_of_date: date,
    lookback_days: int = 365,
    max_business_days: int = 1,
) -> SentimentPulseSeriesResult:
    """Return historical text sentiment only when its latest point is decision-safe."""

    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise ValueError("lookback_days must be an integer")
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if isinstance(max_business_days, bool) or not isinstance(max_business_days, int):
        raise ValueError("max_business_days must be an integer")
    if max_business_days < 0:
        raise ValueError("max_business_days must be non-negative")

    start_date = as_of_date - timedelta(days=lookback_days)
    indices = get_sentiment_index_repository().get_range(start_date, as_of_date)
    if not indices:
        return SentimentPulseSeriesResult(
            points=(),
            observed_at=None,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_index_missing",
        )

    ordered = sorted(indices, key=lambda item: item.index_date)
    latest = ordered[-1]
    observed_at = latest.index_date.date()
    is_stale, _ = sentiment_observation_freshness(
        observed_at,
        as_of_date=as_of_date,
        max_business_days=max_business_days,
    )
    if is_stale:
        return SentimentPulseSeriesResult(
            points=(),
            observed_at=observed_at,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_index_stale",
        )
    if not latest.data_sufficient:
        return SentimentPulseSeriesResult(
            points=(),
            observed_at=observed_at,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_data_insufficient",
        )

    points = tuple(
        SentimentPulsePoint(
            observed_at=index.index_date.date(),
            value=index.composite_index,
        )
        for index in ordered
        if index.data_sufficient
    )
    return SentimentPulseSeriesResult(
        points=points,
        observed_at=observed_at,
        must_not_use_for_decision=False,
        blocked_reason="",
    )
