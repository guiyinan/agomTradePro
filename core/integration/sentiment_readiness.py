"""App-neutral registry for the decision-safe current sentiment reader."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol


class SentimentIndexProjection(Protocol):
    """Minimal display projection consumed by dashboard read surfaces."""

    composite_index: float
    confidence_level: float

    def to_dict(self) -> Mapping[str, object]:
        """Return the canonical display fields for the index."""


class CurrentSentimentProjection(Protocol):
    """Decision-safe current/diagnostic sentiment result."""

    @property
    def index(self) -> SentimentIndexProjection | None:
        """Return the fresh index when decision-safe."""

    @property
    def diagnostic_index(self) -> SentimentIndexProjection | None:
        """Return the latest diagnostic index, even when stale."""

    @property
    def must_not_use_for_decision(self) -> bool:
        """Return the decision safety marker."""

    @property
    def blocked_reason(self) -> str:
        """Return a stable blocker code when the index is unavailable."""


class CurrentSentimentResolver(Protocol):
    """Provider contract registered by the owning Sentiment app."""

    def __call__(
        self,
        *,
        as_of_date: date | None = None,
        max_business_days: int = 1,
    ) -> CurrentSentimentProjection:
        """Resolve one exact current/diagnostic result."""


_resolver: CurrentSentimentResolver | None = None


def register_current_sentiment_resolver(resolver: CurrentSentimentResolver) -> None:
    """Register the owning app's resolver exactly once per process."""

    global _resolver
    if _resolver is not None and _resolver is not resolver:
        raise RuntimeError("current sentiment resolver is already registered")
    _resolver = resolver


def get_current_sentiment_resolver() -> CurrentSentimentResolver:
    """Return the resolver or fail closed before the owning app is ready."""

    if _resolver is None:
        raise RuntimeError("current sentiment resolver is not wired")
    return _resolver


__all__ = [
    "CurrentSentimentProjection",
    "CurrentSentimentResolver",
    "SentimentIndexProjection",
    "get_current_sentiment_resolver",
    "register_current_sentiment_resolver",
]
