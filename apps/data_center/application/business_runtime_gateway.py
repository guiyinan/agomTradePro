"""Consumer-owned gateways for optional business runtime providers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

_pulse_refresher: Callable[..., Any] | None = None
_realtime_price_fetcher: Callable[[list[str]], list[dict[str, Any]]] | None = None
_alpha_homepage_loader: Callable[..., Any] | None = None
_alpha_scope_resolver: Callable[..., Any] | None = None
_alpha_prediction_queuer: Callable[..., Any] | None = None
_alpha_prediction_runner: Callable[..., Any] | None = None


def register_pulse_refresher(provider: Callable[..., Any]) -> None:
    """Register the Pulse snapshot refresh provider."""

    global _pulse_refresher
    _pulse_refresher = provider


def register_realtime_price_fetcher(
    provider: Callable[[list[str]], list[dict[str, Any]]],
) -> None:
    """Register the Realtime latest-price provider."""

    global _realtime_price_fetcher
    _realtime_price_fetcher = provider


def register_alpha_runtime(
    *,
    scope_resolver: Callable[..., Any],
    prediction_queuer: Callable[..., Any],
    prediction_runner: Callable[..., Any],
) -> None:
    """Register Alpha-owned providers used by repair workflows."""

    global _alpha_scope_resolver
    global _alpha_prediction_queuer
    global _alpha_prediction_runner
    _alpha_scope_resolver = scope_resolver
    _alpha_prediction_queuer = prediction_queuer
    _alpha_prediction_runner = prediction_runner


def register_alpha_homepage_loader(provider: Callable[..., Any]) -> None:
    """Register the Dashboard-owned Alpha homepage provider."""

    global _alpha_homepage_loader
    _alpha_homepage_loader = provider


def refresh_pulse_snapshot(*, target_date: date) -> Any:
    """Refresh the Pulse snapshot through its registered provider."""

    if _pulse_refresher is None:
        raise RuntimeError("Pulse snapshot refresh provider is not registered")
    return _pulse_refresher(target_date=target_date)


def fetch_latest_prices(asset_codes: list[str]) -> list[dict[str, Any]]:
    """Fetch latest prices, returning no fallback rows when Realtime is absent."""

    if _realtime_price_fetcher is None:
        return []
    return _realtime_price_fetcher(asset_codes)


def load_alpha_homepage_data(
    *,
    user: Any,
    top_n: int,
    portfolio_id: int,
    pool_mode: str,
) -> Any:
    """Load Alpha homepage data through the registered Dashboard provider."""

    if _alpha_homepage_loader is None:
        raise RuntimeError("Alpha homepage provider is not registered")
    return _alpha_homepage_loader(
        user=user,
        top_n=top_n,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
    )


def resolve_portfolio_alpha_scope(
    *,
    user_id: int,
    portfolio_id: int | None,
    trade_date: date,
    pool_mode: str | None = None,
) -> Any:
    """Resolve an Alpha pool scope through the registered Alpha provider."""

    if _alpha_scope_resolver is None:
        raise RuntimeError("Alpha scope provider is not registered")
    return _alpha_scope_resolver(
        user_id=user_id,
        portfolio_id=portfolio_id,
        trade_date=trade_date,
        pool_mode=pool_mode,
    )


def queue_alpha_score_prediction(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict[str, Any],
) -> Any:
    """Queue Alpha prediction through the registered task provider."""

    if _alpha_prediction_queuer is None:
        raise RuntimeError("Alpha prediction queue provider is not registered")
    return _alpha_prediction_queuer(
        universe_id=universe_id,
        trade_date=trade_date,
        scope_payload=scope_payload,
    )


def run_alpha_score_prediction_now(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict[str, Any],
) -> Any:
    """Run Alpha prediction through the registered task provider."""

    if _alpha_prediction_runner is None:
        raise RuntimeError("Alpha prediction runner is not registered")
    return _alpha_prediction_runner(
        universe_id=universe_id,
        trade_date=trade_date,
        scope_payload=scope_payload,
    )


__all__ = [
    "fetch_latest_prices",
    "load_alpha_homepage_data",
    "queue_alpha_score_prediction",
    "refresh_pulse_snapshot",
    "register_alpha_homepage_loader",
    "register_alpha_runtime",
    "register_pulse_refresher",
    "register_realtime_price_fetcher",
    "resolve_portfolio_alpha_scope",
    "run_alpha_score_prediction_now",
]
