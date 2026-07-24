"""Advisor Sheet intent construction regressions."""

from decimal import Decimal
from types import SimpleNamespace

from apps.decision_rhythm.application.advisor_contracts import AdvisorHoldingSnapshot
from apps.decision_rhythm.application.advisor_sheet_intents import AdvisorSheetIntentMixin


def _holding(weight: str) -> AdvisorHoldingSnapshot:
    return AdvisorHoldingSnapshot(
        asset_code="000001.SH",
        asset_name="Sample",
        asset_class="equity",
        quantity=Decimal("100"),
        market_value=Decimal("1000"),
        current_weight=Decimal(weight),
        avg_cost=Decimal("9"),
        current_price=Decimal("10"),
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=Decimal("10"),
        data_source="test",
        price_time="2026-07-24T00:00:00+00:00",
    )


def _recommendation(side: str) -> SimpleNamespace:
    return SimpleNamespace(
        recommendation_id=f"rec-{side.lower()}",
        security_code="000001.SH",
        side=side,
        stop_loss_price=Decimal("8"),
        position_pct=Decimal("5"),
        human_rationale="test",
    )


def test_reduce_below_weight_cap_becomes_hold() -> None:
    """A zero-delta reduction must not be presented as an order."""
    intent = AdvisorSheetIntentMixin()._build_existing_holding_intent(
        account_id="default",
        holding=_holding("0.10"),
        total_asset=Decimal("10000"),
        recommendation=_recommendation("REDUCE"),
    )

    assert intent is not None
    assert intent.side == "HOLD"
    assert intent.delta_quantity == 0


def test_add_at_weight_cap_becomes_hold() -> None:
    """A holding already above the add cap must not emit an ADD intent."""
    intent = AdvisorSheetIntentMixin()._build_existing_holding_intent(
        account_id="default",
        holding=_holding("0.22"),
        total_asset=Decimal("10000"),
        recommendation=_recommendation("BUY"),
    )

    assert intent is not None
    assert intent.side == "HOLD"
    assert intent.delta_quantity == 0


def test_buy_with_missing_price_is_blocked_without_division() -> None:
    """Missing price must block quantity calculation before division."""
    recommendation = SimpleNamespace(
        recommendation_id="rec-missing-price",
        security_code="000002.SH",
        side="BUY",
        current_price=None,
        entry_price_high=None,
        fair_value=None,
        entry_price_low=None,
        position_pct=Decimal("5"),
        human_rationale="test",
        stop_loss_price=None,
    )

    intent = AdvisorSheetIntentMixin()._build_buy_intent(
        account_id="default",
        recommendation=recommendation,
        holding=None,
        total_asset=Decimal("10000"),
        available_cash=Decimal("5000"),
        asset_name="Sample",
        baseline="existing_positions",
    )

    assert intent is not None
    assert intent.blocking_status == "BLOCKED_PRICE_MISSING"
    assert intent.target_quantity == 0
