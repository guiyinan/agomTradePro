"""Technical registry for optional decision-safe series providers.

The registry lets consumer apps depend on a stable shared contract instead of
importing another business app's implementation directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class DecisionSafeSeriesPoint(Protocol):
    """One source observation supplied through the registry."""

    observed_at: date
    value: float


class DecisionSafeSeriesResult(Protocol):
    """A series together with its explicit decision-safety state."""

    points: tuple[DecisionSafeSeriesPoint, ...]
    observed_at: date | None
    must_not_use_for_decision: bool
    blocked_reason: str


class DecisionSafeSeriesLoader(Protocol):
    """Load an optional series for a requested decision date."""

    def __call__(
        self,
        *,
        as_of_date: date,
        lookback_days: int,
    ) -> DecisionSafeSeriesResult: ...


@dataclass(frozen=True)
class RegisteredDecisionSafeSeriesLoader:
    """The registered loader and the name used for observability."""

    name: str
    loader: DecisionSafeSeriesLoader


_sentiment_series_loader: RegisteredDecisionSafeSeriesLoader | None = None


def register_sentiment_series_loader(
    loader: DecisionSafeSeriesLoader,
) -> None:
    """Register the sentiment implementation at the Django composition root."""

    global _sentiment_series_loader
    _sentiment_series_loader = RegisteredDecisionSafeSeriesLoader(
        name="sentiment",
        loader=loader,
    )


def get_sentiment_series_loader() -> DecisionSafeSeriesLoader | None:
    """Return the optional sentiment loader without importing its app."""

    registration = _sentiment_series_loader
    return registration.loader if registration is not None else None
