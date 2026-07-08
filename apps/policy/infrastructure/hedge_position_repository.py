"""Policy-owned hedge position repository."""

from __future__ import annotations

from typing import Any

from .models import HedgePositionModel


class HedgePositionRepository:
    """Repository for hedge position records."""

    def create_hedge_position(
        self,
        *,
        portfolio_id: int,
        instrument_code: str,
        instrument_type: str,
        hedge_ratio: float,
        hedge_value,
        policy_level: str,
        status: str,
        notes: str,
        execution_price=None,
        opening_cost=None,
        total_cost=None,
        executed_at=None,
    ) -> dict[str, Any]:
        """Create one hedge position row and return a lightweight snapshot."""
        hedge = HedgePositionModel._default_manager.create(
            portfolio_id=portfolio_id,
            instrument_code=instrument_code,
            instrument_type=instrument_type,
            hedge_ratio=hedge_ratio,
            hedge_value=hedge_value,
            policy_level=policy_level,
            status=status,
            notes=notes,
            execution_price=execution_price,
            opening_cost=opening_cost,
            total_cost=total_cost,
            executed_at=executed_at,
        )
        return {
            "id": hedge.id,
            "instrument_code": hedge.instrument_code,
            "hedge_ratio": hedge.hedge_ratio,
            "hedge_value": hedge.hedge_value,
            "execution_price": hedge.execution_price,
            "status": hedge.status,
            "executed_at": hedge.executed_at,
            "total_cost": hedge.total_cost,
            "opening_cost": hedge.opening_cost,
            "closing_cost": hedge.closing_cost,
            "beta_before": hedge.beta_before,
            "beta_after": hedge.beta_after,
            "hedge_profit": hedge.hedge_profit,
        }

    def get_hedge_position(self, *, hedge_id: int, portfolio_id: int) -> dict[str, Any] | None:
        """Return one hedge position snapshot by id and portfolio."""
        hedge = HedgePositionModel._default_manager.filter(
            id=hedge_id,
            portfolio_id=portfolio_id,
        ).first()
        if hedge is None:
            return None
        return {
            "id": hedge.id,
            "portfolio_id": hedge.portfolio_id,
            "instrument_code": hedge.instrument_code,
            "instrument_type": hedge.instrument_type,
            "hedge_ratio": hedge.hedge_ratio,
            "hedge_value": hedge.hedge_value,
            "policy_level": hedge.policy_level,
            "status": hedge.status,
            "execution_price": hedge.execution_price,
            "executed_at": hedge.executed_at,
            "opening_cost": hedge.opening_cost,
            "closing_cost": hedge.closing_cost,
            "total_cost": hedge.total_cost,
            "beta_before": hedge.beta_before,
            "beta_after": hedge.beta_after,
            "hedge_profit": hedge.hedge_profit,
            "notes": hedge.notes,
        }

    def update_beta_metrics(
        self,
        *,
        hedge_id: int,
        beta_before: float,
        beta_after: float,
    ) -> bool:
        """Persist computed beta metrics for one hedge position."""
        return HedgePositionModel._default_manager.filter(id=hedge_id).update(
            beta_before=beta_before,
            beta_after=beta_after,
        ) > 0
