"""Persistence queries and markers for position invalidation state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.infrastructure.models import PositionModel
from apps.simulated_trading.infrastructure.position_mapper import PositionMapper


class PositionInvalidationRepositoryMixin:
    """Keep invalidation-specific repository methods behind the legacy owner."""

    def get_pending_invalidation_positions(self) -> list[Position]:
        """获取需要做证伪检查的持仓。"""
        models = PositionModel._default_manager.filter(
            invalidation_rule_json__isnull=False,
            is_invalidated=False,
        ).exclude(invalidation_rule_json={})
        return [PositionMapper.to_entity(m) for m in models]

    def mark_invalidation_checked(
        self,
        account_id: int,
        asset_code: str,
        checked_at: datetime,
    ) -> bool:
        """Record the latest invalidation check timestamp for one position."""

        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(invalidation_checked_at=checked_at)
        return int(updated) > 0

    def mark_invalidated(
        self,
        account_id: int,
        asset_code: str,
        reason: str,
        checked_at: datetime,
    ) -> bool:
        """Persist the invalidation result and check timestamp for one position."""

        updated = PositionModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).update(
            is_invalidated=True,
            invalidation_reason=reason,
            invalidation_checked_at=checked_at,
        )
        return int(updated) > 0

    def count_positions_with_invalidation_rules(self) -> int:
        """Count positions with a configured invalidation rule."""

        return int(
            PositionModel._default_manager.filter(invalidation_rule_json__isnull=False)
            .exclude(invalidation_rule_json={})
            .count()
        )

    def get_invalidated_position_summaries(self) -> list[dict[str, Any]]:
        """Return active invalidated-position summaries in check-time order."""

        models = (
            PositionModel._default_manager.filter(
                is_invalidated=True,
                quantity__gt=0,
            )
            .select_related("account")
            .order_by("-invalidation_checked_at")
        )
        return [
            {
                "account_id": model.account_id,
                "account_name": model.account.account_name,
                "asset_code": model.asset_code,
                "asset_name": model.asset_name,
                "quantity": model.quantity,
                "market_value": float(model.market_value),
                "unrealized_pnl": float(model.unrealized_pnl),
                "unrealized_pnl_pct": model.unrealized_pnl_pct,
                "invalidation_reason": model.invalidation_reason,
                "invalidation_checked_at": (
                    model.invalidation_checked_at.isoformat()
                    if model.invalidation_checked_at
                    else None
                ),
            }
            for model in models
        ]
