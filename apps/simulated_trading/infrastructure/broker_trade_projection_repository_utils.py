"""Decimal boundary helpers shared by broker projection infrastructure."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from apps.simulated_trading.application.broker_trade_projection import BrokerTradeProjectionConflict

_ZERO = Decimal("0")

_QTY_QUANTUM = Decimal("0.000001")

_PRICE_QUANTUM = Decimal("0.0001")

_MONEY_QUANTUM = Decimal("0.01")


def _decimal(value: object) -> Decimal | None:
    """Convert one ORM decimal-like value without float arithmetic."""

    if value is None:
        return None
    return Decimal(str(value))


def _required_decimal(value: object) -> Decimal:
    """Read a non-null decimal column or raise a stable projection blocker."""

    result = _decimal(value)
    if result is None:
        raise BrokerTradeProjectionConflict("SIM_LEDGER_DECIMAL_MISSING")
    return result


def _money(value: Decimal) -> Decimal:
    """Round an economic value to the Simulated Trading money precision."""

    try:
        return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except ArithmeticError as error:
        raise BrokerTradeProjectionConflict("BROKER_FACT_DECIMAL_OUT_OF_RANGE") from error


def _quantity(value: Decimal) -> Decimal:
    """Round a quantity to the unified position precision."""

    try:
        return value.quantize(_QTY_QUANTUM, rounding=ROUND_HALF_UP)
    except ArithmeticError as error:
        raise BrokerTradeProjectionConflict("BROKER_FACT_DECIMAL_OUT_OF_RANGE") from error


def _fits_decimal_field(value: Decimal, *, max_digits: int, decimal_places: int) -> bool:
    """Check the receiving DecimalField range before issuing an economic write."""

    if not value.is_finite():
        return False
    try:
        quantum = Decimal(1).scaleb(-decimal_places)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return False
    integer_limit = Decimal(10) ** (max_digits - decimal_places)
    return rounded == value and abs(rounded) < integer_limit


def _asset_type_is_supported(asset_type: str) -> bool:
    """Validate the already-mapped value against the receiving model choices."""

    return asset_type in {"equity", "fund", "bond"}
