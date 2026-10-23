"""Pure calculation checks for explicitly entered target differences."""

from decimal import Decimal

from apps.simulated_trading.domain.rebalance_preview_math import (
    calculate_user_target_difference,
)


def test_user_target_difference_selects_buy_without_strategy_threshold() -> None:
    adjustment = calculate_user_target_difference(
        current_quantity=Decimal("0"),
        reference_price=Decimal("20"),
        portfolio_value=Decimal("10000"),
        target_weight=Decimal("0.10"),
    )

    assert adjustment is not None
    assert adjustment.action == "buy"
    assert adjustment.target_amount == Decimal("1000.00")
    assert adjustment.suggested_quantity == Decimal("50.000000")


def test_user_target_difference_selects_risk_reducing_sell() -> None:
    adjustment = calculate_user_target_difference(
        current_quantity=Decimal("100"),
        reference_price=Decimal("20"),
        portfolio_value=Decimal("10000"),
        target_weight=Decimal("0.10"),
    )

    assert adjustment is not None
    assert adjustment.action == "sell"
    assert adjustment.suggested_quantity == Decimal("50.000000")


def test_user_target_difference_holds_exact_target_and_rejects_unknown_quantity() -> None:
    unchanged = calculate_user_target_difference(
        current_quantity=Decimal("50"),
        reference_price=Decimal("20"),
        portfolio_value=Decimal("10000"),
        target_weight=Decimal("0.10"),
    )
    unknown = calculate_user_target_difference(
        current_quantity=None,
        reference_price=Decimal("20"),
        portfolio_value=Decimal("10000"),
        target_weight=Decimal("0.10"),
    )

    assert unchanged is not None
    assert unchanged.action == "hold"
    assert unknown is None


def test_user_target_difference_rejects_invalid_or_missing_valuation_inputs() -> None:
    invalid_target = calculate_user_target_difference(
        current_quantity=Decimal("0"),
        reference_price=Decimal("20"),
        portfolio_value=Decimal("10000"),
        target_weight=Decimal("1.01"),
    )
    missing_value = calculate_user_target_difference(
        current_quantity=Decimal("0"),
        reference_price=Decimal("20"),
        portfolio_value=None,
        target_weight=Decimal("0.10"),
    )

    assert invalid_target is None
    assert missing_value is None
