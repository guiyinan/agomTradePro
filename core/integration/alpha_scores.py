"""Bridge helpers for cross-app alpha score access."""

from __future__ import annotations

from datetime import date


def fetch_stock_scores(*, universe_id: str, intended_trade_date: date, top_n: int = 10):
    """Return alpha stock scores through the owning alpha application service."""

    from apps.alpha.application.services import AlphaService

    return AlphaService().get_stock_scores(
        universe_id=universe_id,
        intended_trade_date=intended_trade_date,
        top_n=top_n,
    )
