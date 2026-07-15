"""Register Alpha runtime services for Data Center repair workflows."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.application.business_runtime_gateway import register_alpha_runtime

from . import pool_resolver, tasks


def _resolve_scope(
    *,
    user_id: int,
    portfolio_id: int | None,
    trade_date: date,
    pool_mode: str | None,
) -> Any:
    return pool_resolver.PortfolioAlphaPoolResolver().resolve(
        user_id=user_id,
        portfolio_id=portfolio_id,
        trade_date=trade_date,
        pool_mode=pool_mode or pool_resolver.ALPHA_POOL_MODE_PRICE_COVERED,
    )


def _queue_prediction(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict[str, Any],
) -> Any:
    return tasks.qlib_predict_scores.apply_async(
        args=[universe_id, trade_date.isoformat(), 30],
        kwargs={"scope_payload": scope_payload},
    )


def _run_prediction(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict[str, Any],
) -> Any:
    return tasks.qlib_predict_scores.apply(
        args=[universe_id, trade_date.isoformat(), 30],
        kwargs={"scope_payload": scope_payload},
    ).get()


def register_alpha_data_center_runtime() -> None:
    """Register Alpha-owned providers while leaving homepage ownership separate."""

    register_alpha_runtime(
        scope_resolver=_resolve_scope,
        prediction_queuer=_queue_prediction,
        prediction_runner=_run_prediction,
    )


__all__ = ["register_alpha_data_center_runtime"]
