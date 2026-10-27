"""Narrow financial invariants for read-only rebalance previews."""

from __future__ import annotations

from decimal import Decimal, Overflow, localcontext

import pytest

from apps.simulated_trading.domain.rebalance_preview_math import (
    account_position_cap_reason,
    account_stop_loss_reason,
    account_total_position_cap_reason,
    calculate_amount_adjustment,
    calculate_asset_adjustment,
    calculate_class_amount,
    calculate_portfolio_value,
    calculate_projected_position_amount,
    constrain_buy_quantity,
    constrain_sell_quantity,
    estimate_plan_funding,
    mark_to_market_amount,
    round_cny_amount,
    strategy_position_cap_reason,
    strategy_stop_loss_reason,
    strategy_total_position_cap_reason,
)


def test_zero_weight_liquidation_keeps_exact_quantity_before_amount_rounding() -> None:
    """A zero target closes the exact holding even below the value drift threshold."""

    adjustment = calculate_asset_adjustment(
        current_quantity=Decimal("3"),
        reference_price=Decimal("7.333"),
        portfolio_value=Decimal("1000000"),
        target_weight=Decimal("0"),
        drift_threshold=Decimal("0.01"),
    )

    assert adjustment is not None
    assert adjustment.action == "sell"
    assert adjustment.current_amount == Decimal("22.00")
    assert adjustment.target_amount == Decimal("0.00")
    assert adjustment.target_quantity == Decimal("0.000000")
    assert adjustment.suggested_quantity == Decimal("3.000000")
    assert adjustment.suggested_amount == Decimal("22.00")


def test_mark_to_market_rounds_the_money_amount_without_changing_quantity() -> None:
    """A source quantity remains exact while its ledger value is rounded to cents."""

    assert mark_to_market_amount(Decimal("3"), Decimal("7.333")) == Decimal("22.00")
    assert mark_to_market_amount(Decimal("0"), Decimal("7.333")) == Decimal("0.00")


@pytest.mark.parametrize(
    ("quantity", "reference_price"),
    [
        (Decimal("-1"), Decimal("5")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("NaN")),
    ],
    ids=("negative-quantity", "zero-price", "nonfinite-price"),
)
def test_mark_to_market_rejects_invalid_financial_inputs(
    quantity: Decimal,
    reference_price: Decimal,
) -> None:
    """A negative holding or unusable quote cannot produce a financial value."""

    assert mark_to_market_amount(quantity, reference_price) is None


@pytest.mark.parametrize(
    ("sell_gross", "sell_fees", "buy_gross", "buy_fees"),
    [
        ((Decimal("100.00"),), (), (), ()),
        ((), (), (Decimal("100.00"),), ()),
        ((Decimal("100.00"),), (Decimal("1.00"), Decimal("2.00")), (), ()),
        ((), (), (Decimal("100.00"),), (Decimal("1.00"), Decimal("2.00"))),
    ],
    ids=("missing-sell-fee", "missing-buy-fee", "extra-sell-fee", "extra-buy-fee"),
)
def test_funding_rejects_fee_and_gross_tuple_length_mismatch(
    sell_gross: tuple[Decimal, ...],
    sell_fees: tuple[Decimal, ...],
    buy_gross: tuple[Decimal, ...],
    buy_fees: tuple[Decimal, ...],
) -> None:
    """A missing per-order fee cannot silently become a zero-fee estimate."""

    estimate = estimate_plan_funding(
        cash_before=Decimal("500.00"),
        sell_gross_values=sell_gross,
        sell_fee_values=sell_fees,
        buy_gross_values=buy_gross,
        buy_fee_values=buy_fees,
    )

    assert estimate.status == "unknown"
    assert estimate.cash_after_buys is None


def test_funding_allows_empty_gross_and_fee_tuples_when_there_are_no_orders() -> None:
    """No orders has an exact zero total, distinct from a missing fee for an order."""

    estimate = estimate_plan_funding(
        cash_before=Decimal("500.00"),
        sell_gross_values=(),
        sell_fee_values=(),
        buy_gross_values=(),
        buy_fee_values=(),
    )

    assert estimate.status == "known"
    assert estimate.sell_gross == Decimal("0.00")
    assert estimate.sell_fees == Decimal("0.00")
    assert estimate.sell_net == Decimal("0.00")
    assert estimate.buy_gross == Decimal("0.00")
    assert estimate.buy_fees == Decimal("0.00")
    assert estimate.buy_total == Decimal("0.00")
    assert estimate.cash_after_sells == Decimal("500.00")
    assert estimate.cash_after_buys == Decimal("500.00")
    assert (
        estimate_plan_funding(
            cash_before=None,
            sell_gross_values=(),
            sell_fee_values=(),
            buy_gross_values=(),
            buy_fee_values=(),
        ).status
        == "unknown"
    )


def test_sell_fees_above_gross_preserve_negative_net_and_cash_shortfall() -> None:
    """An uneconomic sale remains negative rather than becoming free funding."""

    estimate = estimate_plan_funding(
        cash_before=Decimal("0.00"),
        sell_gross_values=(Decimal("1.00"),),
        sell_fee_values=(Decimal("2.00"),),
        buy_gross_values=(),
        buy_fee_values=(),
    )

    assert estimate.status == "shortfall"
    assert estimate.sell_net == Decimal("-1.00")
    assert estimate.cash_after_sells == Decimal("-1.00")
    assert estimate.cash_after_buys == Decimal("-1.00")


def test_funding_keeps_nonfinite_order_amount_unknown() -> None:
    """A nonfinite gross amount cannot be included as known sale funding."""

    estimate = estimate_plan_funding(
        cash_before=Decimal("100.00"),
        sell_gross_values=(Decimal("Infinity"),),
        sell_fee_values=(Decimal("1.00"),),
        buy_gross_values=(),
        buy_fee_values=(),
    )

    assert estimate.status == "unknown"
    assert estimate.sell_gross is None
    assert estimate.sell_net is None
    assert estimate.cash_after_sells is None


def test_class_and_portfolio_value_ignore_price_for_zero_holding_only() -> None:
    """A zero holding needs no quote, while a held asset with no quote blocks totals."""

    holdings = (
        (Decimal("2"), Decimal("4.25")),
        (Decimal("0"), None),
    )

    assert calculate_class_amount(holdings) == Decimal("8.50")
    assert calculate_portfolio_value(cash_before=Decimal("100.00"), holdings=holdings) == Decimal(
        "108.50"
    )
    assert calculate_class_amount(((Decimal("0"), None), (Decimal("1"), None))) is None
    assert calculate_portfolio_value(cash_before=Decimal("0"), holdings=()) is None
    assert (
        calculate_portfolio_value(
            cash_before=Decimal("100.00"),
            holdings=((Decimal("0"), None), (Decimal("1"), None)),
        )
        is None
    )


@pytest.mark.parametrize(
    "holding",
    [
        (None, Decimal("5")),
        (Decimal("-1"), Decimal("5")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("Infinity")),
    ],
    ids=("unknown-quantity", "negative-quantity", "zero-price", "infinite-price"),
)
def test_class_amount_requires_finite_nonnegative_holding_and_positive_price(
    holding: tuple[Decimal | None, Decimal | None],
) -> None:
    """One invalid held component leaves the class amount unknown."""

    assert calculate_class_amount((holding,)) is None


@pytest.mark.parametrize(
    ("cash_before", "holdings"),
    [
        (None, ()),
        (Decimal("-0.01"), ()),
        (Decimal("100"), ((Decimal("-1"), Decimal("5")),)),
        (Decimal("100"), ((Decimal("1"), Decimal("0")),)),
    ],
    ids=("unknown-cash", "negative-cash", "negative-holding", "nonpositive-price"),
)
def test_portfolio_value_stays_unknown_for_invalid_financial_inputs(
    cash_before: Decimal | None,
    holdings: tuple[tuple[Decimal | None, Decimal | None], ...],
) -> None:
    """Invalid cash, quantity, or valuation evidence cannot produce an account total."""

    assert calculate_portfolio_value(cash_before=cash_before, holdings=holdings) is None


def test_amount_adjustment_uses_explicit_weight_as_a_portfolio_fraction() -> None:
    """Class-level amount targets keep weight fractions distinct from strategy percentages."""

    adjustment = calculate_amount_adjustment(
        current_amount=Decimal("300.00"),
        portfolio_value=Decimal("1000.00"),
        target_weight=Decimal("0.50"),
        drift_threshold=Decimal("0.05"),
    )

    assert adjustment.action == "buy"
    assert adjustment.current_weight == Decimal("0.3")
    assert adjustment.target_amount == Decimal("500.00")
    assert adjustment.suggested_amount == Decimal("200.00")


def test_amount_adjustment_holds_at_the_exact_drift_boundary() -> None:
    """A class already inside its declared threshold has no directional action."""

    adjustment = calculate_amount_adjustment(
        current_amount=Decimal("300.00"),
        portfolio_value=Decimal("1000.00"),
        target_weight=Decimal("0.35"),
        drift_threshold=Decimal("0.05"),
    )

    assert adjustment.action == "hold"
    assert adjustment.current_weight == Decimal("0.3")
    assert adjustment.target_amount == Decimal("350.00")
    assert adjustment.suggested_amount == Decimal("50.00")


def test_amount_adjustment_can_reduce_a_class_and_preserve_unknown_delta() -> None:
    """The class target supports a sell direction and never invents a delta without current value."""

    sell = calculate_amount_adjustment(
        current_amount=Decimal("300.00"),
        portfolio_value=Decimal("1000.00"),
        target_weight=Decimal("0.20"),
        drift_threshold=Decimal("0.05"),
    )
    unknown = calculate_amount_adjustment(
        current_amount=None,
        portfolio_value=Decimal("1000.00"),
        target_weight=Decimal("0.20"),
        drift_threshold=Decimal("0.05"),
    )

    assert sell.action == "sell"
    assert sell.target_amount == Decimal("200.00")
    assert sell.suggested_amount == Decimal("100.00")
    assert unknown.action is None
    assert unknown.target_amount == Decimal("200.00")
    assert unknown.suggested_amount is None


def test_strategy_cap_uses_percentage_and_preserves_risk_reducing_sell_context() -> None:
    """Strategy caps are 0–100 percentages while target weights are 0–1 fractions."""

    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.25"),
            max_position_pct=Decimal("25"),
        )
        is None
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.26"),
            max_position_pct=Decimal("25"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.25"),
            max_position_pct=Decimal("0.25"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_position_cap_reason(
            action="sell",
            target_weight=Decimal("0.26"),
            max_position_pct=Decimal("25"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.25"),
            max_position_pct=None,
        )
        == "STRATEGY_MAX_POSITION_LIMIT_UNKNOWN"
    )
    assert (
        strategy_position_cap_reason(
            action="sell",
            target_weight=Decimal("0.26"),
            max_position_pct=None,
        )
        is None
    )


def test_strategy_cap_adds_only_known_active_buy_notional_for_buy_actions() -> None:
    """A matching BUY remainder adds weight; unknown evidence blocks only that BUY."""

    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.05"),
            max_position_pct=Decimal("13.9"),
            active_buy_notional=Decimal("900.00"),
            portfolio_value=Decimal("10000.00"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.05"),
            max_position_pct=Decimal("15"),
            active_buy_notional=Decimal("900.00"),
            portfolio_value=Decimal("10000.00"),
        )
        is None
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.05"),
            max_position_pct=Decimal("15"),
            active_buy_notional=None,
            portfolio_value=Decimal("10000.00"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_UNKNOWN"
    )
    assert (
        strategy_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.05"),
            max_position_pct=Decimal("100"),
            active_buy_notional=Decimal("10000.00"),
            portfolio_value=Decimal("10000.00"),
        )
        == "STRATEGY_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_position_cap_reason(
            action="sell",
            target_weight=Decimal("0.05"),
            max_position_pct=Decimal("6"),
            active_buy_notional=Decimal("900.00"),
            portfolio_value=Decimal("10000.00"),
        )
        is None
    )


def test_strategy_total_position_cap_limits_buy_but_does_not_block_sell() -> None:
    """The existing aggregate percentage cap applies to BUY exposure only."""

    assert (
        strategy_total_position_cap_reason(
            action="buy",
            projected_position_amount=Decimal("500.00"),
            projected_equity=Decimal("1000.00"),
            max_total_position_pct=Decimal("50"),
        )
        is None
    )
    assert (
        strategy_total_position_cap_reason(
            action="buy",
            projected_position_amount=Decimal("500.01"),
            projected_equity=Decimal("1000.00"),
            max_total_position_pct=Decimal("50"),
        )
        == "STRATEGY_MAX_TOTAL_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        strategy_total_position_cap_reason(
            action="buy",
            projected_position_amount=Decimal("500.00"),
            projected_equity=Decimal("1000.00"),
            max_total_position_pct=None,
        )
        == "STRATEGY_MAX_TOTAL_POSITION_LIMIT_UNKNOWN"
    )
    assert (
        strategy_total_position_cap_reason(
            action="sell",
            projected_position_amount=Decimal("500.01"),
            projected_equity=Decimal("1000.00"),
            max_total_position_pct=Decimal("50"),
        )
        is None
    )


def test_asset_target_amount_and_quantity_remain_cent_consistent() -> None:
    """The quantity rounded to storage precision still maps to the rounded target cents."""

    adjustment = calculate_asset_adjustment(
        current_quantity=Decimal("0"),
        reference_price=Decimal("7.333"),
        portfolio_value=Decimal("123456.78"),
        target_weight=Decimal("0.001"),
        drift_threshold=Decimal("0"),
    )

    assert adjustment is not None
    assert adjustment.target_amount == Decimal("123.46")
    assert adjustment.target_quantity is not None
    assert adjustment.suggested_quantity == adjustment.target_quantity
    assert round_cny_amount(adjustment.target_quantity * Decimal("7.333")) == (
        adjustment.target_amount
    )


def test_asset_adjustment_keeps_target_fields_when_current_holding_is_unknown() -> None:
    """A known target may be displayed without inventing a current holding or order delta."""

    adjustment = calculate_asset_adjustment(
        current_quantity=None,
        reference_price=Decimal("5"),
        portfolio_value=Decimal("1000"),
        target_weight=Decimal("0.25"),
        drift_threshold=Decimal("0.01"),
    )

    assert adjustment is not None
    assert adjustment.current_amount is None
    assert adjustment.current_weight is None
    assert adjustment.target_amount == Decimal("250.00")
    assert adjustment.target_quantity == Decimal("50.000000")
    assert adjustment.suggested_amount is None
    assert adjustment.suggested_quantity is None
    assert adjustment.action is None


@pytest.mark.parametrize(
    ("reference_price", "target_weight"),
    [
        (Decimal("NaN"), Decimal("0.25")),
        (Decimal("5"), Decimal("1.01")),
        (Decimal("0"), Decimal("0.25")),
    ],
    ids=("nonfinite-quote", "weight-over-portfolio", "nonpositive-quote"),
)
def test_asset_adjustment_rejects_invalid_price_or_weight(
    reference_price: Decimal,
    target_weight: Decimal,
) -> None:
    """Invalid valuation or target inputs cannot be turned into a suggested order."""

    assert (
        calculate_asset_adjustment(
            current_quantity=Decimal("100"),
            reference_price=reference_price,
            portfolio_value=Decimal("1000"),
            target_weight=target_weight,
            drift_threshold=Decimal("0.01"),
        )
        is None
    )


def test_buy_quantity_rounds_down_to_configured_step_and_maximum() -> None:
    """Configured minimum, increment, and cap constrain the same suggested order."""

    adjustment = constrain_buy_quantity(
        desired_quantity=Decimal("257"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("250"),
    )

    assert adjustment.quantity == Decimal("200")
    assert adjustment.remaining_quantity == Decimal("57")
    assert adjustment.reason_code == "BUY_QUANTITY_MAXIMUM_LIMITED"


@pytest.mark.parametrize(
    ("desired", "maximum", "expected_quantity", "expected_remaining", "expected_reason"),
    [
        (
            "8718.395815",
            "1000000",
            "8700",
            "18.395815",
            "BUY_QUANTITY_STEP_ROUNDED_DOWN",
        ),
        ("250", "250", "200", "50", "BUY_QUANTITY_STEP_ROUNDED_DOWN"),
        ("1000", "1000", "1000", "0", None),
    ],
    ids=("below-maximum-step-rounding", "at-nonstep-maximum", "at-step-aligned-maximum"),
)
def test_buy_quantity_reason_distinguishes_step_rounding_from_maximum_limit(
    desired: str,
    maximum: str,
    expected_quantity: str,
    expected_remaining: str,
    expected_reason: str | None,
) -> None:
    """A remaining fractional lot is not evidence that the order maximum was hit."""

    adjustment = constrain_buy_quantity(
        desired_quantity=Decimal(desired),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal(maximum),
    )

    assert adjustment.quantity == Decimal(expected_quantity)
    assert adjustment.remaining_quantity == Decimal(expected_remaining)
    assert adjustment.reason_code == expected_reason


def test_buy_quantity_below_configured_minimum_is_not_promoted_to_an_order() -> None:
    """A suggestion below the source-backed minimum stays fully non-actionable."""

    adjustment = constrain_buy_quantity(
        desired_quantity=Decimal("99.99"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("1000"),
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("99.99")
    assert adjustment.reason_code == "BUY_QUANTITY_BELOW_RULE_MINIMUM"


def test_buy_quantity_rejects_an_invalid_source_rule() -> None:
    """A zero trading increment cannot be treated as an unconstrained BUY rule."""

    adjustment = constrain_buy_quantity(
        desired_quantity=Decimal("100"),
        minimum=Decimal("100"),
        step=Decimal("0"),
        maximum=Decimal("1000"),
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("100")
    assert adjustment.reason_code == "EXECUTION_QUANTITY_RULE_INVALID"


def test_buy_quantity_rejects_maximum_below_configured_minimum() -> None:
    """An internally contradictory source range cannot produce a BUY quantity."""

    adjustment = constrain_buy_quantity(
        desired_quantity=Decimal("200"),
        minimum=Decimal("200"),
        step=Decimal("100"),
        maximum=Decimal("100"),
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("200")
    assert adjustment.reason_code == "EXECUTION_QUANTITY_RULE_INVALID"


def test_sell_quantity_is_limited_by_known_sellable_balance() -> None:
    """A regular partial sale may not exceed the explicitly sellable quantity."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("300"),
        sellable_quantity=Decimal("200"),
        current_quantity=Decimal("300"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("500"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity == Decimal("200")
    assert adjustment.remaining_quantity == Decimal("100")
    assert adjustment.reason_code == "SELL_QUANTITY_LIMITED_BY_RULE"


def test_explicit_odd_lot_rule_can_close_all_three_shares() -> None:
    """A full close below normal lot size requires the explicit zero-balance rule."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("3"),
        sellable_quantity=Decimal("3"),
        current_quantity=Decimal("3"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("500"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity == Decimal("3")
    assert adjustment.remaining_quantity == Decimal("0")
    assert adjustment.reason_code is None


def test_odd_lot_rule_cannot_masquerade_a_partial_balance_as_full_close() -> None:
    """A restricted sellable balance is not a full-position close and cannot bypass lot rules."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("3"),
        sellable_quantity=Decimal("2"),
        current_quantity=Decimal("3"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("500"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("3")
    assert adjustment.reason_code == "SELL_QUANTITY_NOT_ON_RULE_STEP"


def test_odd_lot_remainder_is_allowed_when_the_entire_position_is_sellable() -> None:
    """The one-time odd remainder exception requires no restricted shares."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("3"),
        sellable_quantity=Decimal("103"),
        current_quantity=Decimal("103"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("10000"),
        odd_lot_mode="SELL_ODD_REMAINDER_ONCE",
    )

    assert adjustment.quantity == Decimal("3")
    assert adjustment.remaining_quantity == Decimal("0")
    assert adjustment.reason_code is None


def test_odd_lot_remainder_is_rejected_when_some_position_is_restricted() -> None:
    """The odd-remainder exception cannot be used while 100 shares remain restricted."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("3"),
        sellable_quantity=Decimal("103"),
        current_quantity=Decimal("203"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("10000"),
        odd_lot_mode="SELL_ODD_REMAINDER_ONCE",
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("3")
    assert adjustment.reason_code == "SELL_ODD_LOT_RESTRICTED_BALANCE"


def test_contradictory_sellable_quantity_cannot_exceed_the_position() -> None:
    """An inconsistent availability input never creates a sale above the holding."""

    current_quantity = Decimal("300")
    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("400"),
        sellable_quantity=Decimal("400"),
        current_quantity=current_quantity,
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("500"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity is None or adjustment.quantity <= current_quantity
    if adjustment.quantity is None:
        assert adjustment.reason_code == "SELLABLE_QUANTITY_EXCEEDS_POSITION"


def test_sell_quantity_rejects_an_invalid_source_rule() -> None:
    """A zero sell increment cannot authorize a position reduction."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("100"),
        sellable_quantity=Decimal("100"),
        current_quantity=Decimal("100"),
        minimum=Decimal("100"),
        step=Decimal("0"),
        maximum=Decimal("1000"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("100")
    assert adjustment.reason_code == "EXECUTION_QUANTITY_RULE_INVALID"


def test_sell_quantity_does_not_create_an_order_for_zero_desired_quantity() -> None:
    """A zero desired sale stays zero rather than becoming the rule minimum."""

    adjustment = constrain_sell_quantity(
        desired_quantity=Decimal("0"),
        sellable_quantity=Decimal("100"),
        current_quantity=Decimal("100"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("1000"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )

    assert adjustment.quantity is None
    assert adjustment.remaining_quantity == Decimal("0")
    assert adjustment.reason_code == "SELL_QUANTITY_BELOW_RULE_MINIMUM"


def test_finite_but_unrepresentable_holding_values_leave_totals_unknown() -> None:
    """Finite inputs that overflow arithmetic cannot become account valuation evidence."""

    extreme = Decimal("1E+999999")
    assert calculate_class_amount(((extreme, extreme),)) is None
    assert (
        calculate_portfolio_value(
            cash_before=Decimal("0.00"),
            holdings=((extreme, extreme),),
        )
        is None
    )


def test_amount_adjustment_rejects_nonfinite_invalid_and_overflowing_inputs() -> None:
    """Invalid weights and an unrepresentable ratio cannot yield a class action."""

    assert (
        calculate_amount_adjustment(
            current_amount=Decimal("NaN"),
            portfolio_value=Decimal("1000"),
            target_weight=Decimal("0.5"),
            drift_threshold=Decimal("0.05"),
        )
        is None
    )
    assert (
        calculate_amount_adjustment(
            current_amount=Decimal("300"),
            portfolio_value=Decimal("1000"),
            target_weight=Decimal("1.01"),
            drift_threshold=Decimal("0.05"),
        )
        is None
    )
    assert (
        calculate_amount_adjustment(
            current_amount=Decimal("1E+999999"),
            portfolio_value=Decimal("1E-999999"),
            target_weight=Decimal("0"),
            drift_threshold=Decimal("0"),
        )
        is None
    )


def test_asset_adjustment_fails_closed_on_arithmetic_and_decimal_context_overflow() -> None:
    """Extreme finite values cannot create a misleading amount or quantity delta."""

    extreme = Decimal("1E+999999")
    assert (
        calculate_asset_adjustment(
            current_quantity=extreme,
            reference_price=extreme,
            portfolio_value=Decimal("1000"),
            target_weight=Decimal("0"),
            drift_threshold=Decimal("0"),
        )
        is None
    )
    with localcontext() as context:
        context.traps[Overflow] = False
        adjustment = calculate_asset_adjustment(
            current_quantity=extreme,
            reference_price=Decimal("1"),
            portfolio_value=Decimal("1E-999999"),
            target_weight=Decimal("0"),
            drift_threshold=Decimal("0"),
        )
    assert adjustment is None


def test_asset_adjustment_holds_at_exact_drift_boundary() -> None:
    """A target exactly on its declared drift boundary requires no direction."""

    adjustment = calculate_asset_adjustment(
        current_quantity=Decimal("50"),
        reference_price=Decimal("10"),
        portfolio_value=Decimal("1000"),
        target_weight=Decimal("0.5"),
        drift_threshold=Decimal("0"),
    )

    assert adjustment is not None
    assert adjustment.action == "hold"
    assert adjustment.suggested_quantity == Decimal("0.000000")


def test_account_position_cap_is_independent_and_unknown_inputs_block_buys() -> None:
    """The account cap remains distinct from Strategy and malformed actions do not pass."""

    assert (
        account_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.20"),
            max_position_pct=Decimal("20"),
        )
        is None
    )
    assert (
        account_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.21"),
            max_position_pct=Decimal("20"),
        )
        == "ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        account_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.10"),
            max_position_pct=Decimal("20"),
            active_buy_notional=Decimal("150.00"),
            portfolio_value=Decimal("1000.00"),
        )
        == "ACCOUNT_MAX_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        account_position_cap_reason(
            action="buy",
            target_weight=None,
            max_position_pct=Decimal("20"),
        )
        == "ACCOUNT_MAX_POSITION_LIMIT_UNKNOWN"
    )
    assert (
        account_position_cap_reason(
            action="reduce",
            target_weight=Decimal("0.21"),
            max_position_pct=Decimal("20"),
        )
        is None
    )


def test_account_total_position_cap_uses_known_projected_equity() -> None:
    """Aggregate BUY exposure is capped while SELL remains risk reducing."""

    assert (
        account_total_position_cap_reason(
            action="buy",
            projected_position_amount=Decimal("500.01"),
            projected_equity=Decimal("1000"),
            max_total_position_pct=Decimal("50"),
        )
        == "ACCOUNT_MAX_TOTAL_POSITION_LIMIT_EXCEEDED"
    )
    assert (
        account_total_position_cap_reason(
            action="buy",
            projected_position_amount=None,
            projected_equity=Decimal("1000"),
            max_total_position_pct=Decimal("50"),
        )
        == "ACCOUNT_MAX_TOTAL_POSITION_LIMIT_UNKNOWN"
    )
    assert (
        account_total_position_cap_reason(
            action="sell",
            projected_position_amount=Decimal("500.01"),
            projected_equity=Decimal("1000"),
            max_total_position_pct=Decimal("50"),
        )
        is None
    )


def test_account_and_strategy_stop_loss_use_percentage_points_and_known_basis() -> None:
    """Configured stop loss blocks only a BUY past the exact existing threshold."""

    for reason_reader, prefix in (
        (account_stop_loss_reason, "ACCOUNT"),
        (strategy_stop_loss_reason, "STRATEGY"),
    ):
        shared = {"current_price": Decimal("94.99"), "average_cost": Decimal("100")}
        assert reason_reader(action="sell", **shared, stop_loss_pct=Decimal("5")) is None
        assert reason_reader(action="buy", **shared, stop_loss_pct=None) is None
        assert reason_reader(action="buy", **shared, stop_loss_pct=Decimal("0")) is None
        assert (
            reason_reader(action="buy", **shared, stop_loss_pct=Decimal("5"))
            == f"{prefix}_STOP_LOSS_TRIGGERED"
        )
        assert (
            reason_reader(
                action="buy",
                current_price=Decimal("95"),
                average_cost=Decimal("100"),
                stop_loss_pct=Decimal("5"),
            )
            is None
        )
        assert (
            reason_reader(
                action="buy",
                current_price=None,
                average_cost=Decimal("100"),
                stop_loss_pct=Decimal("5"),
            )
            == f"{prefix}_STOP_LOSS_EVIDENCE_UNKNOWN"
        )


def test_projected_position_total_requires_every_amount_and_rounds_once() -> None:
    """A total includes every known holding amount and stays unknown on a missing one."""

    assert calculate_projected_position_amount((Decimal("10.005"), Decimal("2.005"))) == Decimal(
        "12.01"
    )
    assert calculate_projected_position_amount(()) == Decimal("0.00")
    assert calculate_projected_position_amount((Decimal("10"), None)) is None
    assert calculate_projected_position_amount((Decimal("-1"),)) is None


def test_quantity_constraints_and_rounding_reject_unrepresentable_values() -> None:
    """Huge quantities and money amounts remain non-actionable when precision is exhausted."""

    extreme = Decimal("1E+999999")
    tiny = Decimal("1E-999999")
    buy = constrain_buy_quantity(
        desired_quantity=extreme,
        minimum=tiny,
        step=tiny,
        maximum=extreme,
    )
    assert buy.quantity is None
    assert buy.reason_code == "EXECUTION_QUANTITY_RULE_INVALID"

    sell = constrain_sell_quantity(
        desired_quantity=Decimal("-1"),
        sellable_quantity=Decimal("100"),
        current_quantity=Decimal("100"),
        minimum=Decimal("100"),
        step=Decimal("100"),
        maximum=Decimal("1000"),
        odd_lot_mode="SELLABLE_BALANCE_TO_ZERO",
    )
    assert sell.quantity is None
    assert sell.reason_code == "EXECUTION_QUANTITY_RULE_INVALID"

    assert round_cny_amount(Decimal("NaN")) is None
    assert round_cny_amount(Decimal("1E+100")) is None
    oversized = calculate_asset_adjustment(
        current_quantity=Decimal("0"),
        reference_price=Decimal("1"),
        portfolio_value=Decimal("1E+100"),
        target_weight=Decimal("1"),
        drift_threshold=Decimal("0"),
    )
    assert oversized is not None
    assert oversized.target_amount is None
    assert oversized.target_quantity is None
    assert oversized.suggested_quantity is None
