"""Alpha runtime bridges used by data_center orchestration."""

from __future__ import annotations

from datetime import date


def resolve_portfolio_alpha_scope(*, user_id: int, portfolio_id: int, trade_date: date):
    """Resolve the portfolio-scoped alpha universe through the owning alpha module."""
    from apps.alpha.application.pool_resolver import PortfolioAlphaPoolResolver

    return PortfolioAlphaPoolResolver().resolve(
        user_id=user_id,
        portfolio_id=portfolio_id,
        trade_date=trade_date,
        pool_mode="price_covered",
    )


def queue_alpha_score_prediction(*, universe_id: str, trade_date: date, scope_payload: dict):
    """Queue scoped alpha score prediction through the owning alpha task."""
    from apps.alpha.application.tasks import qlib_predict_scores

    return qlib_predict_scores.apply_async(
        args=[universe_id, trade_date.isoformat(), 30],
        kwargs={"scope_payload": scope_payload},
    )


def run_alpha_score_prediction_now(
    *,
    universe_id: str,
    trade_date: date,
    scope_payload: dict,
):
    """Run scoped alpha score prediction synchronously through the owning alpha task."""
    from apps.alpha.application.tasks import qlib_predict_scores

    return qlib_predict_scores.apply(
        args=[universe_id, trade_date.isoformat(), 30],
        kwargs={"scope_payload": scope_payload},
    ).get()
