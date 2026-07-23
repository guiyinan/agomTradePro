"""ORM mapping for simulated trade records."""

from __future__ import annotations

from apps.simulated_trading.domain.entities import (
    OrderStatus,
    SimulatedTrade,
    TradeAction,
)

from .models import SimulatedTradeModel


class SimulatedTradeMapper:
    """Map simulated trades between the Domain and Django ORM."""

    @staticmethod
    def to_entity(model: SimulatedTradeModel) -> SimulatedTrade:
        """Convert an ORM trade row to a Domain entity."""

        return SimulatedTrade(
            trade_id=model.id,
            account_id=model.account_id,
            asset_code=model.asset_code,
            asset_name=model.asset_name,
            asset_type=model.asset_type,
            action=TradeAction(model.action),
            quantity=float(model.quantity),
            price=float(model.price),
            amount=float(model.amount),
            commission=float(model.commission),
            slippage=float(model.slippage),
            total_cost=float(model.total_cost),
            realized_pnl=(float(model.realized_pnl) if model.realized_pnl is not None else None),
            realized_pnl_pct=model.realized_pnl_pct,
            reason=model.reason,
            signal_id=model.signal_id,
            order_date=model.order_date,
            execution_date=model.execution_date,
            execution_time=model.execution_time,
            status=OrderStatus(model.status),
        )

    @staticmethod
    def to_model(entity: SimulatedTrade) -> SimulatedTradeModel:
        """Convert a Domain trade entity to an unsaved ORM row."""

        return SimulatedTradeModel(
            id=entity.trade_id,
            account_id=entity.account_id,
            asset_code=entity.asset_code,
            asset_name=entity.asset_name,
            asset_type=entity.asset_type,
            action=entity.action.value,
            quantity=entity.quantity,
            price=entity.price,
            amount=entity.amount,
            commission=entity.commission,
            slippage=entity.slippage,
            total_cost=entity.total_cost,
            realized_pnl=entity.realized_pnl,
            realized_pnl_pct=entity.realized_pnl_pct,
            reason=entity.reason,
            signal_id=entity.signal_id,
            order_date=entity.order_date,
            execution_date=entity.execution_date,
            execution_time=entity.execution_time,
            status=entity.status.value,
        )
