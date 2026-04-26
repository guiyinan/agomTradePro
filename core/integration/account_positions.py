"""Bridge helpers for legacy account position writes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.account.infrastructure.repositories import PositionRepository


def update_or_create_account_position(
    *,
    portfolio_id: int,
    asset_code: str,
    shares: int | float,
    avg_cost: Decimal,
    current_price: Decimal,
    source: str,
) -> Any:
    """Persist one legacy account position through the account repository."""

    position_repo = PositionRepository()
    return position_repo.update_or_create_position(
        portfolio_id=portfolio_id,
        asset_code=asset_code,
        shares=shares,
        avg_cost=avg_cost,
        current_price=current_price,
        source=source,
    )


def list_portfolio_position_weights(portfolio_id: int) -> list[dict[str, Any]]:
    """Return portfolio position weights through the legacy account repository."""

    position_repo = PositionRepository()
    return position_repo.list_portfolio_position_weights(portfolio_id)
