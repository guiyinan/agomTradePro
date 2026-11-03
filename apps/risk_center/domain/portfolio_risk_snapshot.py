"""Exact simulated-account snapshot values and conservative gross exposure math."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class HeldPosition:
    """One exact settled holding; an unresolved ledger identity stays ``None``."""

    asset_code: str
    quantity: Decimal
    available_quantity: Decimal | None
    security_id: str | None = None

    def __post_init__(self) -> None:
        """Reject guessed identities, float quantities, and negative holdings."""

        _require_token(self.asset_code, "asset_code")
        _require_decimal(self.quantity, "quantity", nonnegative=True)
        if self.available_quantity is not None:
            _require_decimal(self.available_quantity, "available_quantity", nonnegative=True)
        if self.security_id is not None:
            _require_token(self.security_id, "security_id")


@dataclass(frozen=True, slots=True)
class OpenOrder:
    """One active reservation with only its known remaining measures populated."""

    order_id: str
    asset_code: str
    security_id: str
    side: OrderSide
    remaining_quantity: Decimal | None
    remaining_amount: Decimal | None
    remaining_cash: Decimal | None = None

    def __post_init__(self) -> None:
        """Validate exact order scope and preserve missing remaining measures."""

        _require_token(self.order_id, "order_id")
        _require_token(self.asset_code, "asset_code")
        _require_token(self.security_id, "security_id")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if self.remaining_quantity is not None:
            _require_decimal(self.remaining_quantity, "remaining_quantity", nonnegative=True)
        if self.remaining_amount is not None:
            _require_decimal(self.remaining_amount, "remaining_amount", nonnegative=True)
        if self.remaining_cash is not None:
            _require_decimal(self.remaining_cash, "remaining_cash", nonnegative=True)


@dataclass(frozen=True, slots=True)
class ProposedOrder:
    """One exact proposed order before the simulated ledger accepts it."""

    order_id: str
    asset_code: str
    security_id: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee_cap: Decimal | None = None

    def __post_init__(self) -> None:
        """Require a positive exact proposed size and price."""

        _require_token(self.order_id, "order_id")
        _require_token(self.asset_code, "asset_code")
        _require_token(self.security_id, "security_id")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        _require_decimal(self.quantity, "quantity", positive=True)
        _require_decimal(self.price, "price", positive=True)
        if self.fee_cap is not None:
            _require_decimal(self.fee_cap, "fee_cap", nonnegative=True)


@dataclass(frozen=True, slots=True)
class ExecutedUsage:
    """One current-session execution sum, retaining unresolved legacy scope."""

    asset_code: str
    security_id: str | None
    execution_session: date | None
    quantity: Decimal | None
    amount: Decimal | None
    complete: bool

    def __post_init__(self) -> None:
        """Keep unknown identity/session/measures visible instead of inventing them."""

        _require_token(self.asset_code, "asset_code")
        if self.security_id is not None:
            _require_token(self.security_id, "security_id")
        if self.execution_session is not None and type(self.execution_session) is not date:
            raise TypeError("execution_session must be a date or None")
        if self.quantity is not None:
            _require_decimal(self.quantity, "quantity", nonnegative=True)
        if self.amount is not None:
            _require_decimal(self.amount, "amount", nonnegative=True)
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")
        if self.complete and (
            self.security_id is None
            or self.execution_session is None
            or (self.quantity is None and self.amount is None)
        ):
            raise ValueError("a complete usage row needs exact identity, session, and measure")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """One owner-scoped, exact preflight snapshot of the simulated account."""

    account_id: int
    owner_user_id: int
    snapshot_id: str
    read_at: datetime
    cash: Decimal | None
    money_unit: str | None
    holdings: tuple[HeldPosition, ...]
    active_orders: tuple[OpenOrder, ...]
    executed_usage: tuple[ExecutedUsage, ...]
    active_orders_complete: bool
    execution_session: date
    executed_usage_complete: bool

    def __post_init__(self) -> None:
        """Validate account scope, clocks, exact values, and collection completeness."""

        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        if type(self.owner_user_id) is not int or self.owner_user_id < 1:
            raise ValueError("owner_user_id must be a positive exact integer")
        _require_token(self.snapshot_id, "snapshot_id")
        _require_aware(self.read_at, "read_at")
        if self.cash is not None:
            _require_decimal(self.cash, "cash")
        if self.money_unit is not None:
            _require_token(self.money_unit, "money_unit")
        if type(self.holdings) is not tuple or any(
            type(item) is not HeldPosition for item in self.holdings
        ):
            raise TypeError("holdings must be a tuple of HeldPosition")
        if type(self.active_orders) is not tuple or any(
            type(item) is not OpenOrder for item in self.active_orders
        ):
            raise TypeError("active_orders must be a tuple of OpenOrder")
        if type(self.executed_usage) is not tuple or any(
            type(item) is not ExecutedUsage for item in self.executed_usage
        ):
            raise TypeError("executed_usage must be a tuple of ExecutedUsage")
        if type(self.active_orders_complete) is not bool:
            raise TypeError("active_orders_complete must be a boolean")
        if type(self.executed_usage_complete) is not bool:
            raise TypeError("executed_usage_complete must be a boolean")
        if type(self.execution_session) is not date:
            raise TypeError("execution_session must be a date")
        order_ids = tuple(item.order_id for item in self.active_orders)
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("active order ids must be unique")


def value_held_quantity(quantity: Decimal, price: Decimal | None) -> Decimal | None:
    """Value a known holding without treating an unknown price as zero."""

    _require_decimal(quantity, "quantity", nonnegative=True)
    if quantity == 0:
        return Decimal("0")
    if price is None:
        return None
    _require_decimal(price, "price", nonnegative=True)
    return exact_decimal_product(quantity, price)


def project_gross_asset_exposure(
    *,
    held_quantity: Decimal,
    active_orders: tuple[OpenOrder, ...],
    proposed_orders: tuple[ProposedOrder, ...],
    qualified_current_price: Decimal | None,
) -> Decimal | None:
    """Add held and pending BUY exposure, using the larger accepted/current value.

    A missing order measure or current price leaves the asset amount unknown. SELL
    orders are deliberately excluded and never release exposure before execution.
    """

    held_value = value_held_quantity(held_quantity, qualified_current_price)
    if held_value is None:
        return None
    if type(active_orders) is not tuple or any(
        type(order) is not OpenOrder for order in active_orders
    ):
        raise TypeError("active_orders must be a tuple of OpenOrder")
    if type(proposed_orders) is not tuple or any(
        type(order) is not ProposedOrder for order in proposed_orders
    ):
        raise TypeError("proposed_orders must be a tuple of ProposedOrder")
    active_buy_orders = tuple(order for order in active_orders if order.side == "buy")
    proposed_buy_orders = tuple(order for order in proposed_orders if order.side == "buy")
    if active_buy_orders or proposed_buy_orders:
        if qualified_current_price is None:
            return None
        _require_decimal(qualified_current_price, "qualified_current_price", nonnegative=True)

    amounts: list[Decimal] = [held_value]
    for order in active_buy_orders:
        if order.remaining_quantity is None or order.remaining_amount is None:
            return None
        if qualified_current_price is None:
            return None
        current_value = exact_decimal_product(order.remaining_quantity, qualified_current_price)
        amounts.append(max(order.remaining_amount, current_value))
    for proposed_order in proposed_buy_orders:
        if qualified_current_price is None:
            return None
        accepted_value = exact_decimal_product(proposed_order.quantity, proposed_order.price)
        current_value = exact_decimal_product(proposed_order.quantity, qualified_current_price)
        amounts.append(max(accepted_value, current_value))
    return exact_decimal_sum(tuple(amounts))


def _require_token(value: str, name: str) -> None:
    if type(value) is not str or not value.strip() or value.strip() != value:
        raise ValueError(f"{name} must be a nonempty trimmed token")


def _require_decimal(
    value: Decimal,
    name: str,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise TypeError(f"{name} must be a finite Decimal")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def exact_decimal_product(left: Decimal, right: Decimal) -> Decimal:
    """Multiply finite Decimal values without context rounding or float conversion."""

    _require_decimal(left, "left")
    _require_decimal(right, "right")
    return _fraction_to_decimal(Fraction(left) * Fraction(right))


def exact_decimal_sum(values: tuple[Decimal, ...]) -> Decimal:
    """Sum finite Decimal values exactly without context rounding."""

    if type(values) is not tuple:
        raise TypeError("values must be a tuple")
    for value in values:
        _require_decimal(value, "sum value")
    return _fraction_to_decimal(sum((Fraction(value) for value in values), Fraction(0)))


def _fraction_to_decimal(value: Fraction) -> Decimal:
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("financial decimal arithmetic produced a non-terminating value")
    scale = max(twos, fives)
    coefficient = value.numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    sign = 1 if coefficient < 0 else 0
    digits_text = str(abs(coefficient))
    digits = tuple(int(character) for character in digits_text)
    return Decimal((sign, digits, -scale))
