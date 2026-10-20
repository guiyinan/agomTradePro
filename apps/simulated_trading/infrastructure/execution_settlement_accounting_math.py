"""Pure accounting calculations shared by settlement execution paths."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from math import isfinite

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)

_MONEY_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.0001")


def _money_sum(*values: Decimal) -> Decimal:
    """Add exact money values and enforce the account/trade column range."""

    with localcontext() as context:
        context.prec = 80
        value = sum(values, Decimal("0")).quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    return validate_ledger_money(value, "ledger_money")


def _money_difference(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Subtract held cash exactly and reject a negative spendable balance."""

    left_value = validate_ledger_money(left, f"{field_name}.total", allow_zero=True)
    right_value = validate_ledger_money(right, f"{field_name}.held", allow_zero=True)
    if right_value > left_value:
        raise SimulatedTradeExecutionBlocked(f"{field_name} is smaller than its active cash holds")
    with localcontext() as context:
        context.prec = 80
        remainder = left_value - right_value
    return validate_ledger_money(remainder, field_name, allow_zero=True)


def _quantity_difference(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Subtract held shares exactly and reject a negative sellable balance."""

    left_value = validate_ledger_quantity(left, f"{field_name}.total", allow_zero=True)
    right_value = validate_ledger_quantity(right, f"{field_name}.held", allow_zero=True)
    if right_value > left_value:
        raise SimulatedTradeExecutionBlocked(
            f"{field_name} is smaller than its active sell reservations"
        )
    with localcontext() as context:
        context.prec = 80
        remainder = left_value - right_value
    return validate_ledger_quantity(remainder, field_name, allow_zero=True)


def _position_available_after_holds(
    *,
    total_quantity: Decimal,
    available_quantity: Decimal,
    held_shares: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return the locked SELL-rule position after exact active-share holds."""

    total = validate_ledger_quantity(total_quantity, "position.quantity")
    available = validate_ledger_quantity(available_quantity, "position.available_quantity")
    held = validate_ledger_quantity(held_shares, "active_order_held_shares", allow_zero=True)
    if held > available:
        raise SimulatedTradeExecutionBlocked(
            "active sell reservations exceed the locked sellable balance",
            code="ORDER_RESERVATION_STATE_INVALID",
        )
    return total, _quantity_difference(
        available,
        held,
        "position.available_quantity_after_reservations",
    )


def _spendable_cash_after_holds(cash: Decimal, held_cash: Decimal) -> Decimal:
    """Return owner cash available to ordinary trades after active BUY holds."""

    current_cash = validate_ledger_money(cash, "account.current_cash")
    held = validate_ledger_money(held_cash, "active_order_held_cash", allow_zero=True)
    if held > current_cash:
        raise SimulatedTradeExecutionBlocked(
            "active order reservations exceed the locked account cash",
            code="ORDER_RESERVATION_STATE_INVALID",
        )
    return _money_difference(current_cash, held, "spendable_cash_after_reservations")


def _require_known_simulated_cash(*, cash_known: bool, reconciliation_status: str) -> None:
    """Fail closed before a trade writes cash without a verified simulated ledger."""

    if (
        type(cash_known) is not bool
        or cash_known is not True
        or type(reconciliation_status) is not str
        or reconciliation_status != "simulated_ledger"
    ):
        raise SimulatedTradeExecutionBlocked(
            "simulated account cash is not a verified ledger balance",
            code="ACCOUNT_CASH_UNKNOWN",
        )


def _require_unreserved_sell_quantity(
    *,
    quantity: Decimal,
    locked_position: tuple[Decimal, Decimal] | None,
    held_shares: Decimal,
) -> None:
    """Reject a SELL that would consume shares reserved by another order."""

    requested = validate_ledger_quantity(quantity, "sell.quantity")
    held = validate_ledger_quantity(held_shares, "active_order_held_shares", allow_zero=True)
    available: Decimal | None = None
    if locked_position is not None:
        if type(locked_position) is not tuple or len(locked_position) != 2:
            raise SimulatedTradeExecutionBlocked(
                "locked sellable position is malformed",
                code="SELLABLE_BALANCE_INVALID",
            )
        available = validate_ledger_quantity(
            locked_position[1],
            "sell.available_after_holds",
            allow_zero=True,
        )
    if available is None or requested > available:
        code = "ORDER_RESERVATION_ACTIVE" if held > 0 else "SELLABLE_BALANCE_INSUFFICIENT"
        raise SimulatedTradeExecutionBlocked(
            "sell quantity exceeds the locked unreserved sellable balance",
            code=code,
        )


def _net_sell_proceeds(amount: Decimal, total_fees: Decimal) -> Decimal:
    """Subtract SELL fees under a wide Decimal context and retain signed proceeds."""

    gross = validate_ledger_money(amount, "sell.amount")
    fees = validate_ledger_money(total_fees, "sell.total_fees", allow_zero=True)
    with localcontext() as context:
        context.prec = 80
        net = gross - fees
    return _signed_money(net, "sell.net_proceeds")


def _rebased_account_market_value(
    aggregate_value: Decimal,
    old_position_value: Decimal,
    new_position_value: Decimal,
) -> Decimal:
    """Replace one revalued position inside the account's aggregate market value."""

    aggregate = validate_ledger_money(aggregate_value, "account.current_market_value")
    old_value = validate_ledger_money(old_position_value, "position.market_value_before_trade")
    new_value = validate_ledger_money(new_position_value, "position.market_value_after_trade")
    if old_value > aggregate:
        raise SimulatedTradeExecutionBlocked(
            "account aggregate market value is smaller than the locked position value"
        )
    return validate_ledger_money(
        aggregate - old_value + new_value,
        "account.current_market_value_after_position_revaluation",
    )


def _allocate_sale_cost_basis(
    *,
    total_cost: Decimal,
    sold_quantity: Decimal,
    total_quantity: Decimal,
) -> Decimal:
    """Allocate stored cost cents proportionally, leaving the final residual intact."""

    if sold_quantity == total_quantity:
        return validate_ledger_money(total_cost, "position.total_cost", allow_zero=False)
    try:
        with localcontext() as context:
            context.prec = 80
            share = (total_cost * sold_quantity / total_quantity).quantize(
                _MONEY_CENT,
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise SimulatedTradeExecutionBlocked(
            "sell cost basis cannot be allocated safely"
        ) from error
    if share <= 0 or share >= total_cost:
        raise SimulatedTradeExecutionBlocked(
            "partial sell cannot preserve a positive cent-denominated remaining cost basis"
        )
    return validate_ledger_money(share, "sell.cost_basis", allow_zero=False)


def _signed_money(value: Decimal, field_name: str) -> Decimal:
    """Round one signed P&L value without applying the nonnegative cash constraint."""

    try:
        with localcontext() as context:
            context.prec = 80
            result = value.quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedTradeExecutionBlocked(
            f"{field_name} cannot be represented at ledger precision"
        ) from error
    if not result.is_finite() or abs(result) >= Decimal("10000000000000"):
        raise SimulatedTradeExecutionBlocked(f"{field_name} exceeds the ledger range")
    return result


def _multiply_money(quantity: Decimal, price: Decimal, field_name: str) -> Decimal:
    """Calculate the cent-rounded market amount using the UoW's declared policy."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = (quantity * price).quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise SimulatedTradeExecutionBlocked(
            f"{field_name} cannot be represented at ledger precision"
        ) from error
    return validate_ledger_money(value, field_name, allow_zero=False)


def _average_cost(total_cost: Decimal, quantity: Decimal) -> Decimal:
    """Return four-decimal average cost from the exact stored cost basis."""

    if quantity <= 0:
        raise SimulatedTradeExecutionBlocked("position quantity must remain positive")
    try:
        with localcontext() as context:
            context.prec = 80
            value = (total_cost / quantity).quantize(_PRICE_TICK, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise SimulatedTradeExecutionBlocked("position average cost is invalid") from error
    return validate_ledger_price(value, "avg_cost", allow_zero=False)


def _percentage(numerator: Decimal, denominator: Decimal) -> float:
    """Convert an exact ledger ratio to the legacy FloatField representation."""

    if denominator <= 0:
        raise SimulatedTradeExecutionBlocked("percentage denominator must be positive")
    with localcontext() as context:
        context.prec = 80
        value = float((numerator / denominator) * Decimal("100"))
    if not isfinite(value):
        raise SimulatedTradeExecutionBlocked("percentage exceeds the persisted float range")
    return value
