"""Simulated Trading-owned adapter for Share account snapshots."""

from __future__ import annotations

from typing import Any

from apps.share.application.account_gateway import register_share_account_gateway
from apps.share.domain.interfaces import (
    ShareOwnedAccountSnapshot,
    ShareOwnedPositionSnapshot,
    ShareOwnedTradeSnapshot,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


class SimulatedTradingShareAccountGateway:
    """Resolve share snapshots from simulated account persistence."""

    def list_owner_accounts(self, owner_id: int) -> list[Any]:
        return list(
            SimulatedAccountModel._default_manager.filter(user_id=owner_id).order_by("-created_at")
        )

    def get_owned_account(
        self, *, owner_id: int, account_id: int
    ) -> ShareOwnedAccountSnapshot | None:
        account = SimulatedAccountModel._default_manager.filter(
            id=account_id, user_id=owner_id
        ).first()
        if account is None:
            return None
        return ShareOwnedAccountSnapshot(
            id=account.id,
            account_name=account.account_name,
            account_type=account.account_type,
            start_date=account.start_date,
            total_value=account.total_value,
            current_market_value=account.current_market_value,
            current_cash=account.current_cash,
            total_return=account.total_return,
            annual_return=account.annual_return,
            max_drawdown=account.max_drawdown,
            sharpe_ratio=account.sharpe_ratio,
            win_rate=account.win_rate,
            total_trades=account.total_trades,
        )

    def list_owned_positions(
        self, *, owner_id: int, account_id: int
    ) -> list[ShareOwnedPositionSnapshot]:
        account = (
            SimulatedAccountModel._default_manager.prefetch_related("positions")
            .filter(id=account_id, user_id=owner_id)
            .first()
        )
        if account is None:
            return []
        return [
            ShareOwnedPositionSnapshot(
                asset_code=position.asset_code,
                asset_name=position.asset_name,
                asset_type=position.asset_type,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                current_price=position.current_price,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                unrealized_pnl_pct=position.unrealized_pnl_pct,
                entry_reason=position.entry_reason,
                invalidation_description=position.invalidation_description,
            )
            for position in account.positions.all().order_by("-market_value")
        ]

    def list_owned_trades(
        self, *, owner_id: int, account_id: int, limit: int
    ) -> list[ShareOwnedTradeSnapshot]:
        account = (
            SimulatedAccountModel._default_manager.prefetch_related("trades")
            .filter(id=account_id, user_id=owner_id)
            .first()
        )
        if account is None:
            return []
        return [
            ShareOwnedTradeSnapshot(
                asset_code=trade.asset_code,
                asset_name=trade.asset_name,
                action=trade.action,
                quantity=trade.quantity,
                price=trade.price,
                amount=trade.amount,
                reason=trade.reason,
                execution_time=trade.execution_time,
                status=trade.status,
            )
            for trade in account.trades.all().order_by("-execution_date", "-execution_time")[:limit]
        ]

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        return SimulatedAccountModel._default_manager.filter(
            id=account_id, user_id=owner_id
        ).exists()


def register_simulated_trading_share_gateway() -> None:
    """Register simulated accounts as the Share account data owner."""

    register_share_account_gateway(SimulatedTradingShareAccountGateway())


__all__ = [
    "SimulatedTradingShareAccountGateway",
    "register_simulated_trading_share_gateway",
]
