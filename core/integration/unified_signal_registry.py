"""App-neutral source providers for unified Signal aggregation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

_alpha_score_fetcher: Callable[..., Any] | None = None
_factor_service_factory: Callable[[], Any] | None = None


def register_alpha_score_fetcher(fetcher: Callable[..., Any]) -> None:
    """Register the Alpha score query."""

    global _alpha_score_fetcher
    _alpha_score_fetcher = fetcher


def register_factor_service_factory(factory: Callable[[], Any]) -> None:
    """Register the Factor integration-service factory."""

    global _factor_service_factory
    _factor_service_factory = factory


def fetch_alpha_scores(*, universe_id: str, intended_trade_date: date, top_n: int) -> Any:
    """Fetch Alpha scores from the registered owner."""

    if _alpha_score_fetcher is None:
        raise ImportError("Alpha score provider is not registered")
    return _alpha_score_fetcher(
        universe_id=universe_id,
        intended_trade_date=intended_trade_date,
        top_n=top_n,
    )


def get_factor_service() -> Any:
    """Build the registered Factor integration service."""

    if _factor_service_factory is None:
        raise ImportError("Factor service provider is not registered")
    return _factor_service_factory()


__all__ = [
    "fetch_alpha_scores",
    "get_factor_service",
    "register_alpha_score_fetcher",
    "register_factor_service_factory",
]
