"""Exact, side-effect-free arithmetic for simulated trade fee corrections.

This module calculates correction deltas and replays a complete average-cost
history. It does not verify source evidence, mutate a Trade, or write a ledger.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import wraps
from typing import ParamSpec, TypeVar

from .execution_settlement_primitives import (
    _MAX_MONEY_VALUE,
    _MONEY_QUANTUM,
    _PRICE_QUANTUM,
    _SHARE_QUANTUM,
    SimulatedSettlementContractError,
    SimulatedTradeSide,
    _require_aware,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)

_MONEY_CENT = _MONEY_QUANTUM
_PRICE_TICK = _PRICE_QUANTUM
_ZERO_MONEY = Decimal("0.00")
_Parameters = ParamSpec("_Parameters")
_Result = TypeVar("_Result")
_WORKING_CONTEXT = Context(
    prec=80,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
with localcontext(_WORKING_CONTEXT):
    _ZERO_QUANTITY = Decimal("0").quantize(_SHARE_QUANTUM)


def _with_fee_context(function: Callable[_Parameters, _Result]) -> Callable[_Parameters, _Result]:
    """Keep validated financial calculations independent of ambient Decimal state."""

    @wraps(function)
    def wrapped(*args: _Parameters.args, **kwargs: _Parameters.kwargs) -> _Result:
        with localcontext(_WORKING_CONTEXT):
            return function(*args, **kwargs)

    return wrapped


class FeeCorrectionContractError(SimulatedSettlementContractError):
    """Raised when a fee correction or cost-replay input is incomplete or invalid."""


def _money_sum(*values: Decimal, field_name: str) -> Decimal:
    """Add ledger money with a wide local context and enforce the stored range."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = sum(values, _ZERO_MONEY).quantize(
                _MONEY_CENT,
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be represented as money") from error
    return validate_ledger_money(value, field_name, allow_zero=True)


def _signed_money_sum(*values: Decimal, field_name: str) -> Decimal:
    """Add signed cent values without applying the nonnegative money validator."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = sum(values, _ZERO_MONEY)
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be calculated") from error
    return _signed_money(value, field_name)


def _signed_money(value: Decimal, field_name: str) -> Decimal:
    """Round one signed ledger delta to cents without rejecting refunds."""

    try:
        with localcontext() as context:
            context.prec = 80
            result = value.quantize(_MONEY_CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be represented as money") from error
    if not result.is_finite() or result.copy_abs() >= _MAX_MONEY_VALUE:
        raise FeeCorrectionContractError(f"{field_name} exceeds the ledger range")
    return _ZERO_MONEY if result.is_zero() else result


def _money_difference(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Subtract two exact amounts without inheriting the caller's Decimal context."""

    try:
        with localcontext() as context:
            context.prec = 80
            result = left - right
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be calculated") from error
    return _signed_money(result, field_name)


@dataclass(frozen=True, slots=True)
class CorrectableFeeComponents:
    """The three fee components eligible for source-proven correction.

    Slippage is intentionally absent and must remain the original simulated
    estimate when a caller builds the effective replay input.
    """

    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal

    @_with_fee_context
    def __post_init__(self) -> None:
        """Require exact, nonnegative cent values for every correctable fee."""

        for field_name, value in (
            ("commission", self.commission),
            ("transfer_fee", self.transfer_fee),
            ("stamp_duty", self.stamp_duty),
        ):
            try:
                validate_ledger_money(value, f"fee.{field_name}", allow_zero=True)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise FeeCorrectionContractError(
                    f"fee.{field_name} is not a valid exact ledger amount"
                ) from error
        _ = self.total

    @property
    @_with_fee_context
    def total(self) -> Decimal:
        """Return the exact total of commission, transfer fee, and stamp duty."""

        return _money_sum(
            self.commission,
            self.transfer_fee,
            self.stamp_duty,
            field_name="correctable_fee_total",
        )


@dataclass(frozen=True, slots=True)
class FeeCorrectionDelta:
    """Signed component deltas and the corresponding account cash movement."""

    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    total_fee_delta: Decimal
    cash_delta: Decimal

    @_with_fee_context
    def __post_init__(self) -> None:
        """Require component totals and cash direction to reconcile exactly."""

        for field_name, value in (
            ("commission", self.commission),
            ("transfer_fee", self.transfer_fee),
            ("stamp_duty", self.stamp_duty),
            ("total_fee_delta", self.total_fee_delta),
            ("cash_delta", self.cash_delta),
        ):
            if type(value) is not Decimal or not value.is_finite():
                raise FeeCorrectionContractError(f"{field_name} must be a finite Decimal")
            if _signed_money(value, field_name) != value:
                raise FeeCorrectionContractError(f"{field_name} must be cent-denominated")
        component_total = _signed_money_sum(
            self.commission,
            self.transfer_fee,
            self.stamp_duty,
            field_name="total_fee_delta",
        )
        if (
            component_total != self.total_fee_delta
            or self.cash_delta != self.total_fee_delta.copy_negate()
        ):
            raise FeeCorrectionContractError("fee and cash deltas do not reconcile")


@dataclass(frozen=True, slots=True)
class FeeCorrectionCashEvent:
    """One separately posted correction cash movement for a financial timeline."""

    event_id: int
    posting_date: date
    posted_at: datetime
    cash_delta: Decimal

    @_with_fee_context
    def __post_init__(self) -> None:
        """Require a stable event identity and an exact signed ledger amount."""

        if type(self.event_id) is not int or self.event_id <= 0:
            raise FeeCorrectionContractError("cash event id must be a positive integer")
        if type(self.posting_date) is not date:
            raise FeeCorrectionContractError("cash event requires an exact posting date")
        try:
            _require_aware(self.posted_at, "cash_event.posted_at")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise FeeCorrectionContractError("cash event posting time must be aware") from error
        if type(self.cash_delta) is not Decimal or not self.cash_delta.is_finite():
            raise FeeCorrectionContractError("cash event delta must be an exact finite Decimal")
        try:
            checked = _signed_money(self.cash_delta, "cash_event.cash_delta")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise FeeCorrectionContractError("cash event delta is invalid") from error
        if checked != self.cash_delta:
            raise FeeCorrectionContractError("cash event delta must be exact cent-denominated")


@_with_fee_context
def calculate_fee_correction_delta(
    previous: CorrectableFeeComponents,
    revised: CorrectableFeeComponents,
) -> FeeCorrectionDelta:
    """Calculate the signed fee change and opposite cash debit/refund.

    The revised amounts must already have been qualified by a source-evidence
    boundary. This function only performs exact arithmetic.
    """

    if (
        type(previous) is not CorrectableFeeComponents
        or type(revised) is not CorrectableFeeComponents
    ):
        raise FeeCorrectionContractError("fee correction requires exact typed fee components")
    previous.__post_init__()
    revised.__post_init__()
    commission_delta = _money_difference(
        revised.commission,
        previous.commission,
        "commission_delta",
    )
    transfer_delta = _money_difference(
        revised.transfer_fee,
        previous.transfer_fee,
        "transfer_fee_delta",
    )
    stamp_delta = _money_difference(
        revised.stamp_duty,
        previous.stamp_duty,
        "stamp_duty_delta",
    )
    total_delta = _signed_money_sum(
        commission_delta,
        transfer_delta,
        stamp_delta,
        field_name="total_fee_delta",
    )
    return FeeCorrectionDelta(
        commission=commission_delta,
        transfer_fee=transfer_delta,
        stamp_duty=stamp_delta,
        total_fee_delta=total_delta,
        cash_delta=_signed_money(total_delta.copy_negate(), "cash_delta"),
    )


@dataclass(frozen=True, slots=True)
class FeeCorrectionReplayTrade:
    """Verified executed-trade values needed for one account/asset cost replay."""

    trade_id: int
    account_id: int
    asset_code: str
    execution_time: datetime
    side: SimulatedTradeSide
    quantity: Decimal
    amount: Decimal
    fee_components: CorrectableFeeComponents
    original_slippage: Decimal
    fee_amounts_known: bool | None
    cost_basis_known: bool | None

    @_with_fee_context
    def __post_init__(self) -> None:
        """Reject untyped or unknown ledger values before replay begins."""

        if type(self.trade_id) is not int or self.trade_id <= 0:
            raise FeeCorrectionContractError("trade_id must be a positive integer")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise FeeCorrectionContractError("account_id must be a positive integer")
        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code.strip() != self.asset_code
            or len(self.asset_code) > 20
            or any(character.isspace() for character in self.asset_code)
        ):
            raise FeeCorrectionContractError("asset_code must be a canonical ledger token")
        try:
            _require_aware(self.execution_time, "execution_time")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise FeeCorrectionContractError("execution_time must be timezone-aware") from error
        if type(self.side) is not SimulatedTradeSide:
            raise FeeCorrectionContractError("side must be a recognized trade side")
        try:
            validate_ledger_quantity(self.quantity, "trade.quantity", allow_zero=False)
            validate_ledger_money(self.amount, "trade.amount", allow_zero=False)
            validate_ledger_money(
                self.original_slippage,
                "trade.original_slippage",
                allow_zero=True,
            )
        except (ArithmeticError, TypeError, ValueError) as error:
            raise FeeCorrectionContractError(
                "trade contains an invalid exact ledger amount"
            ) from error
        if type(self.fee_components) is not CorrectableFeeComponents:
            raise FeeCorrectionContractError("trade fee components must be explicitly typed")
        self.fee_components.__post_init__()
        if self.fee_amounts_known is not True or self.cost_basis_known is not True:
            raise FeeCorrectionContractError("trade fee and cost-basis knowledge must be complete")


@dataclass(frozen=True, slots=True)
class AverageCostReplayStep:
    """Effective position and realized-PnL values after one chronological trade."""

    trade_id: int
    side: SimulatedTradeSide
    quantity_after: Decimal
    total_cost_after: Decimal
    average_cost_after: Decimal | None
    allocated_sale_cost: Decimal | None
    realized_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class AverageCostReplayResult:
    """Complete replay result for one account and one exact asset code."""

    account_id: int
    asset_code: str
    steps: tuple[AverageCostReplayStep, ...]
    ending_quantity: Decimal
    ending_total_cost: Decimal
    ending_average_cost: Decimal | None


def _average_cost(total_cost: Decimal, quantity: Decimal) -> Decimal:
    """Match simulated settlement's four-decimal half-even average-cost rule."""

    if quantity <= 0:
        raise FeeCorrectionContractError("position quantity must remain positive")
    try:
        with localcontext() as context:
            context.prec = 80
            value = (total_cost / quantity).quantize(
                _PRICE_TICK,
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise FeeCorrectionContractError("position average cost cannot be represented") from error
    return validate_ledger_price(value, "position.average_cost", allow_zero=False)


def _quantity_sum(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Add exact six-decimal quantities under a wide local context."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = left + right
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be calculated") from error
    return validate_ledger_quantity(value, field_name, allow_zero=True)


def _quantity_difference(left: Decimal, right: Decimal, field_name: str) -> Decimal:
    """Subtract exact six-decimal quantities under a wide local context."""

    try:
        with localcontext() as context:
            context.prec = 80
            value = left - right
    except (InvalidOperation, OverflowError) as error:
        raise FeeCorrectionContractError(f"{field_name} cannot be calculated") from error
    return validate_ledger_quantity(value, field_name, allow_zero=True)


def _allocate_sale_cost_basis(
    *,
    total_cost: Decimal,
    sold_quantity: Decimal,
    total_quantity: Decimal,
) -> Decimal:
    """Match settlement's cent allocation and preserve the final residual."""

    if sold_quantity == total_quantity:
        return validate_ledger_money(total_cost, "position.total_cost", allow_zero=False)
    try:
        with localcontext() as context:
            context.prec = 80
            allocated = (total_cost * sold_quantity / total_quantity).quantize(
                _MONEY_CENT,
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError, ZeroDivisionError) as error:
        raise FeeCorrectionContractError("sale cost basis cannot be allocated") from error
    if allocated <= 0 or allocated >= total_cost:
        raise FeeCorrectionContractError(
            "partial sale cannot preserve a positive cent-denominated cost basis"
        )
    return validate_ledger_money(allocated, "sale.allocated_cost", allow_zero=False)


@_with_fee_context
def replay_average_cost_history(
    trades: Sequence[FeeCorrectionReplayTrade],
) -> AverageCostReplayResult:
    """Replay a complete known account/asset history with effective fee overlays.

    Callers must provide every executed trade affecting the asset, with each
    trade's current effective commission/transfer/stamp values and its original
    slippage estimate. The function sorts deterministically by execution time
    and Trade ID, rejects unknown fee/basis rows, and never mutates inputs.
    """

    if not isinstance(trades, Sequence) or isinstance(trades, (str, bytes)):
        raise FeeCorrectionContractError("trades must be a typed sequence")
    if not trades:
        raise FeeCorrectionContractError("complete trade history cannot be empty")
    checked_trades: list[FeeCorrectionReplayTrade] = []
    for trade in trades:
        if type(trade) is not FeeCorrectionReplayTrade:
            raise FeeCorrectionContractError("trade history contains an untyped row")
        trade.__post_init__()
        checked_trades.append(trade)

    account_id = checked_trades[0].account_id
    asset_code = checked_trades[0].asset_code
    if any(
        trade.account_id != account_id or trade.asset_code != asset_code for trade in checked_trades
    ):
        raise FeeCorrectionContractError("trade history crosses account or asset scope")
    trade_ids = [trade.trade_id for trade in checked_trades]
    if len(set(trade_ids)) != len(trade_ids):
        raise FeeCorrectionContractError("trade history contains duplicate trade IDs")
    try:
        ordered_trades = sorted(
            checked_trades,
            key=lambda trade: (trade.execution_time, trade.trade_id),
        )
    except (TypeError, ValueError) as error:
        raise FeeCorrectionContractError("trade history has incomparable timestamps") from error

    quantity = _ZERO_QUANTITY
    total_cost = _ZERO_MONEY
    steps: list[AverageCostReplayStep] = []
    for trade in ordered_trades:
        fees = _money_sum(
            trade.fee_components.commission,
            trade.fee_components.transfer_fee,
            trade.fee_components.stamp_duty,
            trade.original_slippage,
            field_name="effective_trade_fees",
        )
        if trade.side is SimulatedTradeSide.BUY:
            trade_cost = _money_sum(trade.amount, fees, field_name="buy.total_cost")
            quantity = _quantity_sum(
                quantity,
                trade.quantity,
                "position.quantity_after_buy",
            )
            total_cost = _money_sum(
                total_cost, trade_cost, field_name="position.total_cost_after_buy"
            )
            steps.append(
                AverageCostReplayStep(
                    trade_id=trade.trade_id,
                    side=trade.side,
                    quantity_after=quantity,
                    total_cost_after=total_cost,
                    average_cost_after=_average_cost(total_cost, quantity),
                    allocated_sale_cost=None,
                    realized_pnl=None,
                )
            )
            continue

        if trade.quantity > quantity:
            raise FeeCorrectionContractError("sell quantity exceeds replayed holdings")
        allocated_cost = _allocate_sale_cost_basis(
            total_cost=total_cost,
            sold_quantity=trade.quantity,
            total_quantity=quantity,
        )
        realized_pnl = _signed_money(
            _money_difference(
                _money_difference(trade.amount, fees, "sell.net_proceeds"),
                allocated_cost,
                "sell.realized_pnl",
            ),
            "sell.realized_pnl",
        )
        quantity = _quantity_difference(
            quantity,
            trade.quantity,
            "position.quantity_after_sell",
        )
        total_cost = _money_sum(
            _money_difference(total_cost, allocated_cost, "position.cost_after_sell"),
            field_name="position.total_cost_after_sell",
        )
        average_cost = _average_cost(total_cost, quantity) if quantity > 0 else None
        steps.append(
            AverageCostReplayStep(
                trade_id=trade.trade_id,
                side=trade.side,
                quantity_after=quantity,
                total_cost_after=total_cost,
                average_cost_after=average_cost,
                allocated_sale_cost=allocated_cost,
                realized_pnl=realized_pnl,
            )
        )

    return AverageCostReplayResult(
        account_id=account_id,
        asset_code=asset_code,
        steps=tuple(steps),
        ending_quantity=quantity,
        ending_total_cost=total_cost,
        ending_average_cost=_average_cost(total_cost, quantity) if quantity > 0 else None,
    )


__all__ = [
    "AverageCostReplayResult",
    "AverageCostReplayStep",
    "CorrectableFeeComponents",
    "FeeCorrectionCashEvent",
    "FeeCorrectionContractError",
    "FeeCorrectionDelta",
    "FeeCorrectionReplayTrade",
    "calculate_fee_correction_delta",
    "replay_average_cost_history",
]
