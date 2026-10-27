"""Pure weight, quantity, and funding calculations for plan previews."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Literal

_MONEY_QUANTUM = Decimal("0.01")
_QUANTITY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class AssetAdjustment:
    """One finite target-weight calculation in account currency and units."""

    action: Literal["buy", "sell", "hold"] | None
    current_amount: Decimal | None
    current_weight: Decimal | None
    target_amount: Decimal | None
    target_quantity: Decimal | None
    suggested_amount: Decimal | None
    suggested_quantity: Decimal | None


@dataclass(frozen=True, slots=True)
class FundingEstimate:
    """Cash projection from explicit notional and fee inputs only."""

    status: Literal["known", "shortfall", "unknown"]
    sell_gross: Decimal | None
    sell_fees: Decimal | None
    sell_net: Decimal | None
    cash_after_sells: Decimal | None
    buy_gross: Decimal | None
    buy_fees: Decimal | None
    buy_total: Decimal | None
    cash_after_buys: Decimal | None


@dataclass(frozen=True, slots=True)
class AmountAdjustment:
    """One portfolio-amount target calculation without asset quantities."""

    action: Literal["buy", "sell", "hold"] | None
    current_amount: Decimal | None
    current_weight: Decimal | None
    target_amount: Decimal | None
    suggested_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class QuantityConstraintAdjustment:
    """A single suggested order quantity constrained by source-backed rule terms."""

    quantity: Decimal | None
    remaining_quantity: Decimal | None
    reason_code: str | None


def calculate_class_amount(
    holdings: tuple[tuple[Decimal | None, Decimal | None], ...],
) -> Decimal | None:
    """Sum one class from exact quantity/price pairs; any held unknown blocks the sum."""

    try:
        total = Decimal("0")
        for quantity, reference_price in holdings:
            if quantity is None or not quantity.is_finite() or quantity < 0:
                return None
            if quantity == 0:
                continue
            if reference_price is None or not reference_price.is_finite() or reference_price <= 0:
                return None
            total += quantity * reference_price
        return round_cny_amount(total)
    except ArithmeticError:
        return None


def calculate_portfolio_value(
    *,
    cash_before: Decimal | None,
    holdings: tuple[tuple[Decimal | None, Decimal | None], ...],
) -> Decimal | None:
    """Mark cash and all held positions at the same quote cutoff, or leave total unknown."""

    if cash_before is None or not cash_before.is_finite() or cash_before < 0:
        return None
    try:
        total = cash_before
        for quantity, reference_price in holdings:
            if quantity is None or not quantity.is_finite() or quantity < 0:
                return None
            if quantity == 0:
                continue
            if reference_price is None or not reference_price.is_finite() or reference_price <= 0:
                return None
            total += quantity * reference_price
        rounded = round_cny_amount(total)
        return rounded if rounded is not None and rounded > 0 else None
    except ArithmeticError:
        return None


def calculate_amount_adjustment(
    *,
    current_amount: Decimal | None,
    portfolio_value: Decimal | None,
    target_weight: Decimal | None,
    drift_threshold: Decimal | None,
) -> AmountAdjustment | None:
    """Calculate a class-level amount target from the same marked portfolio total."""

    values = tuple(
        value
        for value in (current_amount, portfolio_value, target_weight, drift_threshold)
        if value is not None
    )
    if any(not value.is_finite() for value in values):
        return None
    if (
        current_amount is not None
        and current_amount < 0
        or portfolio_value is not None
        and portfolio_value <= 0
        or target_weight is not None
        and not Decimal("0") <= target_weight <= Decimal("1")
        or drift_threshold is not None
        and drift_threshold < 0
    ):
        return None
    try:
        current_weight = (
            current_amount / portfolio_value
            if current_amount is not None and portfolio_value is not None
            else None
        )
        target_amount = (
            round_cny_amount(portfolio_value * target_weight)
            if portfolio_value is not None and target_weight is not None
            else None
        )
        suggested_amount = (
            round_cny_amount(abs(target_amount - current_amount))
            if target_amount is not None and current_amount is not None
            else None
        )
    except ArithmeticError:
        return None
    action: Literal["buy", "sell", "hold"] | None = None
    if current_weight is not None and target_weight is not None and drift_threshold is not None:
        drift = target_weight - current_weight
        action = "hold" if abs(drift) <= drift_threshold else "buy" if drift > 0 else "sell"
    return AmountAdjustment(
        action=action,
        current_amount=current_amount,
        current_weight=current_weight,
        target_amount=target_amount,
        suggested_amount=suggested_amount,
    )


def calculate_asset_adjustment(
    *,
    current_quantity: Decimal | None,
    reference_price: Decimal | None,
    portfolio_value: Decimal | None,
    target_weight: Decimal | None,
    drift_threshold: Decimal | None,
) -> AssetAdjustment | None:
    """Calculate supported fields independently and leave missing inputs unknown."""

    values = tuple(
        value
        for value in (
            current_quantity,
            reference_price,
            portfolio_value,
            target_weight,
            drift_threshold,
        )
        if value is not None
    )
    if any(not value.is_finite() for value in values):
        return None
    if (
        current_quantity is not None
        and current_quantity < 0
        or reference_price is not None
        and reference_price <= 0
        or portfolio_value is not None
        and portfolio_value <= 0
        or target_weight is not None
        and not Decimal("0") <= target_weight <= Decimal("1")
        or drift_threshold is not None
        and drift_threshold < 0
    ):
        return None

    try:
        raw_current_amount = (
            current_quantity * reference_price
            if current_quantity is not None and reference_price is not None
            else None
        )
        current_amount = (
            round_cny_amount(raw_current_amount) if raw_current_amount is not None else None
        )
        current_weight = (
            raw_current_amount / portfolio_value
            if raw_current_amount is not None and portfolio_value is not None
            else None
        )
        raw_target_amount = (
            portfolio_value * target_weight
            if portfolio_value is not None and target_weight is not None
            else Decimal("0") if target_weight == Decimal("0") else None
        )
        target_amount = (
            round_cny_amount(raw_target_amount) if raw_target_amount is not None else None
        )
        raw_target_quantity = (
            raw_target_amount / reference_price
            if raw_target_amount is not None and reference_price is not None and reference_price > 0
            else Decimal("0") if target_weight == Decimal("0") else None
        )
        target_quantity = (
            _quantity(raw_target_quantity) if raw_target_quantity is not None else None
        )
        raw_suggested_amount = (
            abs(raw_target_amount - raw_current_amount)
            if raw_target_amount is not None and raw_current_amount is not None
            else None
        )
        suggested_amount = (
            round_cny_amount(raw_suggested_amount) if raw_suggested_amount is not None else None
        )
        raw_suggested_quantity = (
            abs(raw_target_quantity - current_quantity)
            if raw_target_quantity is not None and current_quantity is not None
            else None
        )
        suggested_quantity = (
            _quantity(raw_suggested_quantity) if raw_suggested_quantity is not None else None
        )
    except ArithmeticError:
        return None
    if any(
        value is not None and not value.is_finite()
        for value in (
            current_amount,
            current_weight,
            target_amount,
            target_quantity,
            suggested_amount,
            suggested_quantity,
        )
    ):
        return None
    action: Literal["buy", "sell", "hold"] | None = None
    if target_weight == Decimal("0") and current_quantity is not None and current_quantity > 0:
        action = "sell"
    elif current_weight is not None and target_weight is not None and drift_threshold is not None:
        drift = target_weight - current_weight
        if abs(drift) <= drift_threshold:
            action = "hold"
        else:
            action = "buy" if drift > 0 else "sell"
    return AssetAdjustment(
        action=action,
        current_amount=current_amount,
        current_weight=current_weight,
        target_amount=target_amount,
        target_quantity=target_quantity,
        suggested_amount=suggested_amount,
        suggested_quantity=suggested_quantity,
    )


def calculate_user_target_difference(
    *,
    current_quantity: Decimal | None,
    reference_price: Decimal | None,
    portfolio_value: Decimal | None,
    target_weight: Decimal | None,
) -> AssetAdjustment | None:
    """Calculate a direct quantity difference for an explicitly supplied target.

    This path has no strategy drift trigger. It derives only the direction from
    exact current and target quantities; every valuation input remains subject
    to the same validation as the ordinary asset adjustment.
    """

    adjustment = calculate_asset_adjustment(
        current_quantity=current_quantity,
        reference_price=reference_price,
        portfolio_value=portfolio_value,
        target_weight=target_weight,
        drift_threshold=None,
    )
    if (
        adjustment is None
        or current_quantity is None
        or adjustment.target_quantity is None
        or adjustment.suggested_quantity is None
    ):
        return None
    if adjustment.target_quantity == current_quantity:
        action: Literal["buy", "sell", "hold"] = "hold"
    elif adjustment.target_quantity > current_quantity:
        action = "buy"
    else:
        action = "sell"
    return AssetAdjustment(
        action=action,
        current_amount=adjustment.current_amount,
        current_weight=adjustment.current_weight,
        target_amount=adjustment.target_amount,
        target_quantity=adjustment.target_quantity,
        suggested_amount=adjustment.suggested_amount,
        suggested_quantity=adjustment.suggested_quantity,
    )


def strategy_position_cap_reason(
    *,
    action: str,
    target_weight: Decimal | None,
    max_position_pct: Decimal | None,
    active_buy_notional: Decimal | None = Decimal("0.00"),
    portfolio_value: Decimal | None = None,
) -> str | None:
    """Check projected same-asset exposure against the Strategy percentage cap.

    Strategy stores the cap as a percentage from 0 to 100, while preview target
    weights are portfolio fractions from 0 to 1. A missing cap prevents a BUY
    from being called ready. For BUYs, a caller may add the accurately known
    remaining notional of active same-asset BUY reservations. A SELL that
    reduces an over-cap position remains available and never offsets a hold.
    """

    return _position_cap_reason_with_active_buy(
        prefix="STRATEGY",
        action=action,
        target_weight=target_weight,
        max_position_pct=max_position_pct,
        active_buy_notional=active_buy_notional,
        portfolio_value=portfolio_value,
    )


def account_position_cap_reason(
    *,
    action: str,
    target_weight: Decimal | None,
    max_position_pct: Decimal | None,
    active_buy_notional: Decimal | None = Decimal("0.00"),
    portfolio_value: Decimal | None = None,
) -> str | None:
    """Check projected same-asset exposure against the locked account cap."""

    return _position_cap_reason_with_active_buy(
        prefix="ACCOUNT",
        action=action,
        target_weight=target_weight,
        max_position_pct=max_position_pct,
        active_buy_notional=active_buy_notional,
        portfolio_value=portfolio_value,
    )


def _position_cap_reason_with_active_buy(
    *,
    prefix: str,
    action: str,
    target_weight: Decimal | None,
    max_position_pct: Decimal | None,
    active_buy_notional: Decimal | None,
    portfolio_value: Decimal | None,
) -> str | None:
    """Add known same-asset BUY remainder to a BUY cap input only."""

    base_reason = _position_cap_reason(
        prefix=prefix,
        action=action,
        target_weight=target_weight,
        max_position_pct=max_position_pct,
    )
    if action != "buy" or base_reason is not None:
        return base_reason
    if (
        type(active_buy_notional) is not Decimal
        or not active_buy_notional.is_finite()
        or active_buy_notional < 0
    ):
        return f"{prefix}_MAX_POSITION_LIMIT_UNKNOWN"
    if active_buy_notional == 0:
        return None
    if (
        type(portfolio_value) is not Decimal
        or not portfolio_value.is_finite()
        or portfolio_value <= 0
        or target_weight is None
    ):
        return f"{prefix}_MAX_POSITION_LIMIT_UNKNOWN"
    try:
        projected_weight = target_weight + active_buy_notional / portfolio_value
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return f"{prefix}_MAX_POSITION_LIMIT_UNKNOWN"
    if not projected_weight.is_finite():
        return f"{prefix}_MAX_POSITION_LIMIT_UNKNOWN"
    if projected_weight > 1:
        return f"{prefix}_MAX_POSITION_LIMIT_EXCEEDED"
    return _position_cap_reason(
        prefix=prefix,
        action=action,
        target_weight=projected_weight,
        max_position_pct=max_position_pct,
    )


def _position_cap_reason(
    *,
    prefix: str,
    action: str,
    target_weight: Decimal | None,
    max_position_pct: Decimal | None,
) -> str | None:
    """Apply one named source's existing per-asset percentage cap."""

    if action not in {"buy", "sell", "hold"}:
        return None
    if (
        target_weight is None
        or max_position_pct is None
        or not target_weight.is_finite()
        or not max_position_pct.is_finite()
        or target_weight < 0
        or target_weight > 1
        or max_position_pct < 0
        or max_position_pct > 100
    ):
        return f"{prefix}_MAX_POSITION_LIMIT_UNKNOWN" if action == "buy" else None
    if target_weight * Decimal("100") > max_position_pct:
        return f"{prefix}_MAX_POSITION_LIMIT_EXCEEDED"
    return None


def strategy_total_position_cap_reason(
    *,
    action: str,
    projected_position_amount: Decimal | None,
    projected_equity: Decimal | None,
    max_total_position_pct: Decimal | None,
) -> str | None:
    """Check a BUY against the existing Strategy total-position percentage cap."""

    return _total_position_cap_reason(
        prefix="STRATEGY",
        action=action,
        projected_position_amount=projected_position_amount,
        projected_equity=projected_equity,
        max_total_position_pct=max_total_position_pct,
    )


def account_total_position_cap_reason(
    *,
    action: str,
    projected_position_amount: Decimal | None,
    projected_equity: Decimal | None,
    max_total_position_pct: Decimal | None,
) -> str | None:
    """Check projected total holdings against the locked account's cap."""

    return _total_position_cap_reason(
        prefix="ACCOUNT",
        action=action,
        projected_position_amount=projected_position_amount,
        projected_equity=projected_equity,
        max_total_position_pct=max_total_position_pct,
    )


def _total_position_cap_reason(
    *,
    prefix: str,
    action: str,
    projected_position_amount: Decimal | None,
    projected_equity: Decimal | None,
    max_total_position_pct: Decimal | None,
) -> str | None:
    """Apply one named source's existing total-position percentage cap."""

    if action != "buy":
        return None
    if (
        projected_position_amount is None
        or projected_equity is None
        or max_total_position_pct is None
        or not projected_position_amount.is_finite()
        or not projected_equity.is_finite()
        or not max_total_position_pct.is_finite()
        or projected_position_amount < 0
        or projected_equity <= 0
        or max_total_position_pct < 0
        or max_total_position_pct > 100
    ):
        return f"{prefix}_MAX_TOTAL_POSITION_LIMIT_UNKNOWN"
    if projected_position_amount * Decimal("100") > projected_equity * max_total_position_pct:
        return f"{prefix}_MAX_TOTAL_POSITION_LIMIT_EXCEEDED"
    return None


def account_stop_loss_reason(
    *,
    action: str,
    current_price: Decimal | None,
    average_cost: Decimal | None,
    stop_loss_pct: Decimal | None,
) -> str | None:
    """Block a BUY when the configured account stop-loss has already fired.

    The account setting is stored in percentage points, matching the existing
    simulated-account exit rule. A risk-reducing SELL remains available.
    """

    return _stop_loss_reason(
        prefix="ACCOUNT",
        action=action,
        current_price=current_price,
        average_cost=average_cost,
        stop_loss_pct=stop_loss_pct,
    )


def strategy_stop_loss_reason(
    *,
    action: str,
    current_price: Decimal | None,
    average_cost: Decimal | None,
    stop_loss_pct: Decimal | None,
) -> str | None:
    """Block a BUY when the configured Strategy stop-loss has already fired."""

    return _stop_loss_reason(
        prefix="STRATEGY",
        action=action,
        current_price=current_price,
        average_cost=average_cost,
        stop_loss_pct=stop_loss_pct,
    )


def _stop_loss_reason(
    *,
    prefix: str,
    action: str,
    current_price: Decimal | None,
    average_cost: Decimal | None,
    stop_loss_pct: Decimal | None,
) -> str | None:
    """Apply an existing source's percentage-point account/strategy limit."""

    if action != "buy" or stop_loss_pct is None or stop_loss_pct == 0:
        return None
    if (
        not stop_loss_pct.is_finite()
        or stop_loss_pct < 0
        or current_price is None
        or average_cost is None
        or not current_price.is_finite()
        or not average_cost.is_finite()
        or current_price <= 0
        or average_cost <= 0
    ):
        return f"{prefix}_STOP_LOSS_EVIDENCE_UNKNOWN"
    pnl_pct = (current_price - average_cost) * Decimal("100") / average_cost
    if pnl_pct < -stop_loss_pct:
        return f"{prefix}_STOP_LOSS_TRIGGERED"
    return None


def calculate_projected_position_amount(amounts: tuple[Decimal | None, ...]) -> Decimal | None:
    """Sum the target and retained holding amounts only when every value is known."""

    if any(amount is None or not amount.is_finite() or amount < 0 for amount in amounts):
        return None
    return round_cny_amount(sum((amount for amount in amounts if amount is not None), Decimal("0")))


def estimate_plan_funding(
    *,
    cash_before: Decimal | None,
    sell_gross_values: tuple[Decimal | None, ...],
    sell_fee_values: tuple[Decimal | None, ...],
    buy_gross_values: tuple[Decimal | None, ...],
    buy_fee_values: tuple[Decimal | None, ...],
) -> FundingEstimate:
    """Estimate cash after sells and buys, keeping every unknown input unknown."""

    if len(sell_gross_values) != len(sell_fee_values) or len(buy_gross_values) != len(
        buy_fee_values
    ):
        return FundingEstimate(
            status="unknown",
            sell_gross=None,
            sell_fees=None,
            sell_net=None,
            cash_after_sells=None,
            buy_gross=None,
            buy_fees=None,
            buy_total=None,
            cash_after_buys=None,
        )

    sell_known = all(value is not None and value.is_finite() for value in sell_gross_values)
    sell_fees_known = all(value is not None and value.is_finite() for value in sell_fee_values)
    buy_known = all(value is not None and value.is_finite() for value in buy_gross_values)
    buy_fees_known = all(value is not None and value.is_finite() for value in buy_fee_values)
    sell_gross = _sum_known(sell_gross_values) if sell_known else None
    sell_fees = _sum_known(sell_fee_values) if sell_fees_known else None
    sell_net = sell_gross - sell_fees if sell_gross is not None and sell_fees is not None else None
    cash_after_sells = (
        cash_before + sell_net
        if cash_before is not None and cash_before.is_finite() and sell_net is not None
        else None
    )
    buy_gross = _sum_known(buy_gross_values) if buy_known else None
    buy_fees = _sum_known(buy_fee_values) if buy_fees_known else None
    buy_total = buy_gross + buy_fees if buy_gross is not None and buy_fees is not None else None
    cash_after_buys = (
        cash_after_sells - buy_total
        if cash_after_sells is not None and buy_total is not None
        else None
    )
    status: Literal["known", "shortfall", "unknown"]
    if cash_after_sells is None or buy_total is None or cash_after_buys is None:
        status = "unknown"
    else:
        status = "shortfall" if cash_after_buys < 0 else "known"
    return FundingEstimate(
        status=status,
        sell_gross=sell_gross,
        sell_fees=sell_fees,
        sell_net=sell_net,
        cash_after_sells=cash_after_sells,
        buy_gross=buy_gross,
        buy_fees=buy_fees,
        buy_total=buy_total,
        cash_after_buys=cash_after_buys,
    )


def constrain_buy_quantity(
    *,
    desired_quantity: Decimal,
    minimum: Decimal,
    step: Decimal,
    maximum: Decimal,
) -> QuantityConstraintAdjustment:
    """Round a BUY suggestion down to an explicitly configured order increment."""

    values = (desired_quantity, minimum, step, maximum)
    if any(not value.is_finite() for value in values) or any(value <= 0 for value in values):
        return QuantityConstraintAdjustment(
            None, desired_quantity, "EXECUTION_QUANTITY_RULE_INVALID"
        )
    if maximum < minimum:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "EXECUTION_QUANTITY_RULE_INVALID"
        )
    capped = min(desired_quantity, maximum)
    try:
        quantity = (capped / step).to_integral_value(rounding=ROUND_DOWN) * step
    except ArithmeticError:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "EXECUTION_QUANTITY_RULE_INVALID"
        )
    if quantity < minimum:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "BUY_QUANTITY_BELOW_RULE_MINIMUM"
        )
    remaining = max(desired_quantity - quantity, Decimal("0"))
    if remaining == 0:
        reason = None
    elif desired_quantity > maximum:
        reason = "BUY_QUANTITY_MAXIMUM_LIMITED"
    else:
        reason = "BUY_QUANTITY_STEP_ROUNDED_DOWN"
    return QuantityConstraintAdjustment(quantity, remaining, reason)


def constrain_sell_quantity(
    *,
    desired_quantity: Decimal,
    sellable_quantity: Decimal,
    current_quantity: Decimal,
    minimum: Decimal,
    step: Decimal,
    maximum: Decimal,
    odd_lot_mode: str,
) -> QuantityConstraintAdjustment:
    """Constrain a SELL to configured lot terms and explicit odd-lot semantics."""

    values = (
        desired_quantity,
        sellable_quantity,
        current_quantity,
        minimum,
        step,
        maximum,
    )
    if any(not value.is_finite() for value in values) or any(value < 0 for value in values):
        return QuantityConstraintAdjustment(
            None, desired_quantity, "EXECUTION_QUANTITY_RULE_INVALID"
        )
    if sellable_quantity > current_quantity:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "SELLABLE_QUANTITY_EXCEEDS_POSITION"
        )
    if minimum <= 0 or step <= 0 or maximum < minimum:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "EXECUTION_QUANTITY_RULE_INVALID"
        )
    candidate = min(desired_quantity, sellable_quantity, maximum)
    if candidate <= 0:
        return QuantityConstraintAdjustment(
            None, desired_quantity, "SELL_QUANTITY_BELOW_RULE_MINIMUM"
        )
    on_step = candidate % step == 0
    regular_order = on_step and candidate >= minimum
    clear_to_zero = (
        odd_lot_mode == "SELLABLE_BALANCE_TO_ZERO"
        and candidate == sellable_quantity
        and candidate == current_quantity
    )
    one_odd_remainder = (
        odd_lot_mode == "SELL_ODD_REMAINDER_ONCE"
        and candidate <= sellable_quantity
        and sellable_quantity == current_quantity
        and (sellable_quantity - candidate) % step == 0
    )
    if not (regular_order or clear_to_zero or one_odd_remainder):
        if (
            odd_lot_mode == "SELL_ODD_REMAINDER_ONCE"
            and candidate <= sellable_quantity
            and candidate % step != 0
            and (sellable_quantity - candidate) % step == 0
            and sellable_quantity < current_quantity
        ):
            return QuantityConstraintAdjustment(
                None, desired_quantity, "SELL_ODD_LOT_RESTRICTED_BALANCE"
            )
        reason = (
            "SELL_QUANTITY_NOT_ON_RULE_STEP" if not on_step else "SELL_QUANTITY_BELOW_RULE_MINIMUM"
        )
        return QuantityConstraintAdjustment(None, desired_quantity, reason)
    remaining = max(desired_quantity - candidate, Decimal("0"))
    limit_reason: str | None = "SELL_QUANTITY_LIMITED_BY_RULE" if remaining > 0 else None
    return QuantityConstraintAdjustment(candidate, remaining, limit_reason)


def mark_to_market_amount(quantity: Decimal, reference_price: Decimal) -> Decimal | None:
    """Return one nonnegative holding value at a validated positive reference price."""

    if (
        not quantity.is_finite()
        or not reference_price.is_finite()
        or quantity < 0
        or reference_price <= 0
    ):
        return None
    return round_cny_amount(quantity * reference_price)


def round_cny_amount(value: Decimal) -> Decimal | None:
    """Round one finite CNY amount to ledger cents using half-even rounding."""

    if not value.is_finite():
        return None
    try:
        result = value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _quantity(value: Decimal) -> Decimal | None:
    """Round down to the position quantity field's six-place precision."""

    try:
        result = value.quantize(_QUANTITY_QUANTUM, rounding=ROUND_DOWN)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _sum_known(values: tuple[Decimal | None, ...]) -> Decimal:
    """Sum a sequence already checked to contain only finite Decimal values."""

    return sum((value for value in values if value is not None), Decimal("0.00"))


__all__: tuple[str, ...] = (
    "AssetAdjustment",
    "FundingEstimate",
    "QuantityConstraintAdjustment",
    "calculate_asset_adjustment",
    "calculate_projected_position_amount",
    "account_position_cap_reason",
    "account_total_position_cap_reason",
    "account_stop_loss_reason",
    "constrain_buy_quantity",
    "constrain_sell_quantity",
    "calculate_user_target_difference",
    "estimate_plan_funding",
    "mark_to_market_amount",
    "round_cny_amount",
    "strategy_position_cap_reason",
    "strategy_stop_loss_reason",
    "strategy_total_position_cap_reason",
)
