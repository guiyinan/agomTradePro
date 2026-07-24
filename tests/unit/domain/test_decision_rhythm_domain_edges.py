"""Quota, cooldown, valuation, and approval boundaries for Decision Rhythm."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_rhythm.domain.rhythm_entities import (
    CooldownPeriod,
    DecisionQuota,
    QuotaPeriod,
    QuotaStatus,
)
from apps.decision_rhythm.domain.valuation_entities import (
    ApprovalStatus,
    ExecutionApprovalRequest,
    InvestmentRecommendation,
    RecommendationSide,
)


def test_quota_zero_capacity_over_limit_reset_and_legacy_execution_count() -> None:
    """Quota status and backward-compatible capacity remain deterministic."""
    zero = DecisionQuota(
        period=QuotaPeriod.DAILY,
        max_decisions=0,
        max_executions=2,
    )
    assert zero.max_execution_count == 2
    assert zero.utilization_rate == 1.0
    assert zero.status == QuotaStatus.EXHAUSTED

    near = DecisionQuota(
        period=QuotaPeriod.WEEKLY,
        max_decisions=10,
        max_execution_count=10,
        used_decisions=9,
        used_executions=1,
    )
    assert near.status == QuotaStatus.OVER_LIMIT
    reset = near.reset()
    assert reset.used_decisions == 0
    assert reset.used_executions == 0
    assert reset.period_start is not None
    assert reset.period_end is not None


def test_quota_period_end_covers_daily_weekly_monthly_december_and_unknown() -> None:
    """Every governed quota period has an explicit reset boundary."""
    now = datetime(2026, 12, 31, 10, tzinfo=UTC)
    assert DecisionQuota(QuotaPeriod.DAILY, 1, 1)._calculate_period_end(now) == now.replace(
        hour=23, minute=59, second=59
    )
    weekly_end = DecisionQuota(QuotaPeriod.WEEKLY, 1, 1)._calculate_period_end(now)
    assert weekly_end is not None and weekly_end > now
    monthly_end = DecisionQuota(QuotaPeriod.MONTHLY, 1, 1)._calculate_period_end(now)
    assert monthly_end == datetime(2027, 1, 1, 10, tzinfo=UTC)


def test_quota_serialization_expiry_and_consumption() -> None:
    """Quota snapshots expose remaining capacity, expiry, and immutable updates."""
    now = datetime.now(UTC)
    quota = DecisionQuota(
        period=QuotaPeriod.DAILY,
        max_decisions=2,
        max_execution_count=2,
        period_end=now - timedelta(seconds=1),
    )
    assert quota.is_expired is True
    assert quota.days_remaining == 0
    assert quota.consume_decision().used_decisions == 1
    assert quota.consume_execution().used_executions == 1
    assert quota.to_dict()["is_expired"] is True

    no_end = DecisionQuota(QuotaPeriod.DAILY, 2, 2)
    assert no_end.is_expired is False
    assert no_end.days_remaining is None


def test_cooldown_missing_recent_and_elapsed_times() -> None:
    """Decision and execution cooldowns expose readiness and remaining hours."""
    empty = CooldownPeriod("000001.SZ")
    assert empty.is_decision_ready is True
    assert empty.is_execution_ready is True
    assert empty.decision_ready_in_hours == 0
    assert empty.execution_ready_in_hours == 0

    recent = CooldownPeriod(
        "000001.SZ",
        last_decision_at=datetime.now(UTC) - timedelta(hours=1),
        last_execution_at=datetime.now(UTC) - timedelta(hours=1),
        min_decision_interval_hours=24,
        min_execution_interval_hours=48,
    )
    assert recent.is_decision_ready is False
    assert recent.is_execution_ready is False
    assert 22 < recent.decision_ready_in_hours <= 23.1
    assert 46 < recent.execution_ready_in_hours <= 47.1

    elapsed = CooldownPeriod(
        "000001.SZ",
        last_decision_at=datetime.now(UTC) - timedelta(hours=25),
        last_execution_at=datetime.now(UTC) - timedelta(hours=49),
        min_decision_interval_hours=24,
        min_execution_interval_hours=48,
    )
    assert elapsed.is_decision_ready is True
    assert elapsed.is_execution_ready is True
    assert elapsed.decision_ready_in_hours == 0
    assert elapsed.execution_ready_in_hours == 0
    assert recent.update_decision_time().last_decision_at is not None
    assert recent.update_execution_time().last_execution_at is not None
    assert recent.to_dict()["asset_code"] == "000001.SZ"


def _recommendation(side: RecommendationSide) -> InvestmentRecommendation:
    """Build a complete valuation recommendation."""
    return InvestmentRecommendation(
        recommendation_id="rec-1",
        security_code="000001.SZ",
        side=side.value,
        confidence=0.8,
        valuation_method="DCF",
        fair_value=Decimal("100"),
        entry_price_low=Decimal("90"),
        entry_price_high=Decimal("110"),
        target_price_low=Decimal("120"),
        target_price_high=Decimal("130"),
        stop_loss_price=Decimal("80"),
        position_size_pct=0.1,
        max_capital=Decimal("10000"),
        reason_codes=["VALUATION_LOW"],
        human_readable_rationale="fresh valuation",
        account_id="account-1",
        valuation_snapshot_id="snapshot-1",
        source_recommendation_ids=[],
        created_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_investment_recommendation_price_and_serialization_contracts() -> None:
    """Buy/sell recommendations enforce their respective price boundaries."""
    buy = _recommendation(RecommendationSide.BUY)
    sell = _recommendation(RecommendationSide.SELL)
    assert buy.is_buy is True and buy.is_sell is False
    assert sell.is_sell is True and sell.is_buy is False
    assert buy.suggested_quantity == 100
    assert buy.price_range["stop_loss"] == Decimal("80")
    assert buy.validate_buy_price(Decimal("111"))[0] is False
    assert buy.validate_buy_price(Decimal("110")) == (True, "价格合理")
    assert sell.validate_buy_price(Decimal("100")) == (False, "非买入建议")
    assert buy.validate_sell_price(Decimal("120")) == (False, "非卖出建议")
    assert sell.validate_sell_price(Decimal("100"), triggered_by_risk=True) == (
        True,
        "风控触发卖出",
    )
    assert sell.validate_sell_price(Decimal("119"))[0] is False
    assert sell.validate_sell_price(Decimal("120")) == (True, "价格合理")
    assert buy.to_dict()["suggested_quantity"] == 100

    zero_entry = InvestmentRecommendation(
        **{
            **buy.__dict__,
            "entry_price_low": Decimal("0"),
            "entry_price_high": Decimal("0"),
        }
    )
    assert zero_entry.suggested_quantity == 0


@pytest.mark.parametrize(
    ("side", "market_price", "expected"),
    [
        (RecommendationSide.BUY, Decimal("111"), False),
        (RecommendationSide.BUY, Decimal("110"), True),
        (RecommendationSide.SELL, Decimal("999"), True),
    ],
)
def test_execution_approval_price_validation_and_status(
    side: RecommendationSide,
    market_price: Decimal,
    expected: bool,
) -> None:
    """Approval respects buy caps while allowing risk-driven sells."""
    request = ExecutionApprovalRequest(
        request_id="approval-1",
        recommendation_id="rec-1",
        plan_id=None,
        account_id="account-1",
        security_code="000001.SZ",
        side=side.value,
        approval_status=ApprovalStatus.PENDING,
        suggested_quantity=100,
        market_price_at_review=None,
        price_range_low=Decimal("90"),
        price_range_high=Decimal("110"),
        stop_loss_price=Decimal("80"),
        risk_check_results={},
        reviewer_comments="",
        regime_source="V2",
        created_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert request.is_pending is True
    assert request.validate_price_for_approval(market_price)[0] is expected
    assert request.aggregation_key == "account-1:000001.SZ:" + side.value
    assert request.to_dict()["approval_status"] == ApprovalStatus.PENDING.value
