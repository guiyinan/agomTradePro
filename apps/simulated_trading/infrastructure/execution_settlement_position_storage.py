"""Account-locked position storage for exact simulated trade settlement."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.risk_center.domain.execution_trading_constraints import ExecutionDenyCode
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    validate_ledger_money,
    validate_ledger_quantity,
)
from apps.simulated_trading.infrastructure.execution_settlement_accounting_math import (
    _allocate_sale_cost_basis,
    _average_cost,
    _money_sum,
    _multiply_money,
    _percentage,
    _quantity_difference,
    _signed_money,
)
from apps.simulated_trading.infrastructure.execution_settlement_position_validation import (
    validate_execution_position as _validate_execution_position,
)
from apps.simulated_trading.infrastructure.models import PositionModel


def _apply_buy_position(
    *,
    using: str,
    position: PositionModel | None,
    intent: SimulatedTradeIntent,
    total_cost: Decimal,
    market_session: date,
    released_immediately: bool,
) -> PositionModel:
    """Add an exact buy while preserving every preexisting sellable share."""

    if type(intent) is not SimulatedTradeIntent:
        raise SimulatedTradeExecutionBlocked("buy position requires a typed order intent")
    new_quantity = intent.quantity
    market_value = _multiply_money(new_quantity, intent.price, "position.market_value")
    if position is None:
        avg_cost = _average_cost(total_cost, new_quantity)
        return PositionModel._default_manager.using(using).create(
            account_id=intent.account_id,
            asset_code=intent.asset_code,
            asset_name=intent.asset_name,
            asset_type=intent.asset_type,
            quantity=new_quantity,
            available_quantity=(new_quantity if released_immediately else Decimal("0")),
            available_quantity_known=True,
            avg_cost=avg_cost,
            total_cost=total_cost,
            cost_basis_known=True,
            current_price=intent.price,
            market_value=market_value,
            unrealized_pnl=market_value - total_cost,
            unrealized_pnl_pct=_percentage(market_value - total_cost, total_cost),
            first_buy_date=market_session,
            signal_id=intent.signal_id,
            entry_reason=intent.reason,
        )
    _validate_execution_position(position)
    if position.is_invalidated:
        raise SimulatedTradeExecutionBlocked("invalidated position cannot receive a new buy")
    if position.asset_type != intent.asset_type:
        raise SimulatedTradeExecutionBlocked("position asset type differs from buy intent")
    old_quantity = validate_ledger_quantity(position.quantity, "position.quantity")
    old_available = validate_ledger_quantity(
        position.available_quantity,
        "position.available_quantity",
    )
    old_cost = validate_ledger_money(position.total_cost, "position.total_cost")
    next_quantity = validate_ledger_quantity(
        old_quantity + new_quantity,
        "position.quantity_after_buy",
        allow_zero=False,
    )
    next_cost = _money_sum(old_cost, total_cost)
    next_market_value = _multiply_money(next_quantity, intent.price, "position.market_value")
    next_avg_cost = _average_cost(next_cost, next_quantity)
    next_available = validate_ledger_quantity(
        old_available + (new_quantity if released_immediately else Decimal("0")),
        "position.available_quantity_after_buy",
    )
    if next_available > next_quantity:
        raise SimulatedTradeExecutionBlocked("buy would corrupt sellable quantity")
    position.quantity = next_quantity
    position.available_quantity = next_available
    position.avg_cost = next_avg_cost
    position.total_cost = next_cost
    # A complete new lot does not certify any pre-existing unknown basis.
    position.current_price = intent.price
    position.market_value = next_market_value
    position.unrealized_pnl = next_market_value - next_cost
    position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, next_cost)
    position.last_update_date = market_session
    position.signal_id = intent.signal_id
    position.entry_reason = intent.reason or position.entry_reason
    position.save(
        using=using,
        update_fields=[
            "quantity",
            "available_quantity",
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "last_update_date",
            "signal_id",
            "entry_reason",
        ],
    )
    return position


def _apply_sell_position(
    *,
    using: str,
    position: PositionModel,
    intent: SimulatedTradeIntent,
    amount: Decimal,
    total_cost: Decimal,
    market_session: date,
) -> tuple[PositionModel | None, Decimal | None, float | None]:
    """Sell only explicitly available shares and preserve exact remaining cost basis."""

    if type(intent) is not SimulatedTradeIntent:
        raise SimulatedTradeExecutionBlocked("sell position requires a typed order intent")
    _validate_execution_position(position)
    if position.asset_type != intent.asset_type:
        raise SimulatedTradeExecutionBlocked("position asset type differs from sell intent")
    quantity = validate_ledger_quantity(position.quantity, "position.quantity")
    available = validate_ledger_quantity(
        position.available_quantity,
        "position.available_quantity",
    )
    if intent.quantity > available:
        raise SimulatedTradeExecutionBlocked(
            "sell quantity exceeds explicitly available shares",
            code=ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT.value,
        )
    if intent.quantity > quantity:
        raise SimulatedTradeExecutionBlocked("sell quantity exceeds total shares")
    stored_cost = validate_ledger_money(
        position.total_cost,
        "position.total_cost",
        allow_zero=False,
    )
    cost_basis = _allocate_sale_cost_basis(
        total_cost=stored_cost,
        sold_quantity=intent.quantity,
        total_quantity=quantity,
    )
    if position.cost_basis_known is True:
        realized_pnl = _signed_money(amount - total_cost - cost_basis, "realized_pnl")
        realized_pct = _percentage(realized_pnl, cost_basis)
    else:
        realized_pnl = None
        realized_pct = None
    remaining = validate_ledger_quantity(
        quantity - intent.quantity,
        "position.quantity_after_sell",
    )
    if remaining == 0:
        position.delete(using=using)
        return None, realized_pnl, realized_pct
    remaining_cost = validate_ledger_money(
        stored_cost - cost_basis,
        "position.remaining_cost_basis",
        allow_zero=False,
    )
    remaining_market_value = _multiply_money(
        remaining,
        intent.price,
        "position.market_value_after_sell",
    )
    position.quantity = remaining
    position.available_quantity = validate_ledger_quantity(
        _quantity_difference(
            available,
            intent.quantity,
            "position.available_quantity_after_sell",
        ),
        "position.available_quantity_after_sell",
    )
    position.avg_cost = _average_cost(remaining_cost, remaining)
    position.total_cost = remaining_cost
    position.current_price = intent.price
    position.market_value = remaining_market_value
    position.unrealized_pnl = remaining_market_value - remaining_cost
    position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, remaining_cost)
    position.last_update_date = market_session
    position.save(
        using=using,
        update_fields=[
            "quantity",
            "available_quantity",
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "last_update_date",
        ],
    )
    return position, realized_pnl, realized_pct
