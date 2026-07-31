"""Technical registry for optional decision-safe series providers.

The registry lets consumer apps depend on a stable shared contract instead of
importing another business app's implementation directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class DecisionSafeSeriesPoint(Protocol):
    """One source observation supplied through the registry."""

    @property
    def observed_at(self) -> date: ...

    @property
    def value(self) -> float: ...


class DecisionSafeSeriesResult(Protocol):
    """A series together with its explicit decision-safety state."""

    @property
    def points(self) -> Sequence[DecisionSafeSeriesPoint]: ...

    @property
    def observed_at(self) -> date | None: ...

    @property
    def must_not_use_for_decision(self) -> bool: ...

    @property
    def blocked_reason(self) -> str: ...


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
