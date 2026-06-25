from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from apps.decision_rhythm.application.advisor_services import (
    AdvisorAccountSnapshot,
    AdvisorHoldingSnapshot,
    GenerateAdvisorDecisionSheetUseCase,
)


class FakeHoldingProvider:
    def __init__(self, snapshot: AdvisorAccountSnapshot):
        self.snapshot = snapshot

    def get_snapshot(self, *, account_id: str, user):
        return self.snapshot


class FakeRecommendationProvider:
    def __init__(self, recommendations):
        self.recommendations = recommendations

    def list_recommendations(self, *, account_id: str):
        return self.recommendations


def _snapshot(*, holdings, baseline="existing_positions", cash="20000"):
    return AdvisorAccountSnapshot(
        account_summary={
            "account_id": "1",
            "account_name": "Growth Account",
            "account_type": "simulated",
            "account_type_label": "模拟盘账户",
            "account_status": "active",
            "total_asset": 100000.0,
            "cash": float(Decimal(cash)),
            "available_cash": float(Decimal(cash)),
            "market_value": 80000.0,
            "holding_count": len(holdings),
            "baseline": baseline,
        },
        holdings=holdings,
        baseline=baseline,
    )


def _holding(code, *, weight, quantity="100", price="10", pnl_pct="0"):
    return AdvisorHoldingSnapshot(
        asset_code=code,
        asset_name=code,
        asset_class="equity",
        quantity=Decimal(quantity),
        market_value=Decimal("100000") * Decimal(weight),
        current_weight=Decimal(weight),
        avg_cost=Decimal("8"),
        current_price=Decimal(price) if price is not None else None,
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=Decimal(pnl_pct),
        data_source="unified",
        price_time="2026-06-25T09:30:00+08:00",
    )


def _rec(code, side="BUY", *, price="10", quantity=0, rationale="candidate"):
    return SimpleNamespace(
        recommendation_id=f"rec_{code}_{side}",
        security_code=code,
        side=side,
        human_rationale=rationale,
        fair_value=Decimal(price or "0"),
        entry_price_low=Decimal(price or "0"),
        entry_price_high=Decimal(price or "0"),
        stop_loss_price=Decimal("0"),
        position_pct=5.0,
        suggested_quantity=quantity,
    )


def _execute(snapshot, recommendations):
    use_case = GenerateAdvisorDecisionSheetUseCase(
        holding_provider=FakeHoldingProvider(snapshot),
        recommendation_provider=FakeRecommendationProvider(recommendations),
    )
    return use_case.execute(account_id="1", user=object())


def test_existing_positions_prioritize_exit_and_reduce_before_new_buy():
    sheet = _execute(
        _snapshot(
            holdings=[
                _holding("AAA", weight="0.30", quantity="300", price="100"),
                _holding("BBB", weight="0.08", quantity="200", price="40", pnl_pct="-12"),
            ]
        ),
        [_rec("CCC", "BUY", price="20")],
    )

    assert sheet["today_conclusion"] == "ACT"
    sides = [item["side"] for item in sheet["order_intents"][:3]]
    assert sides == ["EXIT", "REDUCE", "BUY"]
    assert sheet["order_intents"][0]["asset_code"] == "BBB"
    assert sheet["order_intents"][1]["asset_code"] == "AAA"
    assert sheet["order_summary"]["buy"] == 1
    assert sheet["order_summary"]["reduce"] == 1
    assert sheet["order_summary"]["exit"] == 1


def test_empty_account_builds_starter_buy_from_cash_and_target_weight():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="50000"),
        [_rec("CCC", "BUY", price="25", quantity=0)],
    )

    assert sheet["baseline"] == "empty_positions"
    assert sheet["today_conclusion"] == "ACT"
    order = sheet["order_intents"][0]
    assert order["side"] == "BUY"
    assert order["delta_quantity"] == 200.0
    assert order["estimated_amount"] == 5000.0
    assert "recommendation_quantity_zero_recomputed" in ";".join(sheet["warnings"])


def test_zero_quantity_recommendation_is_recomputed_not_shown_as_zero_order():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("DDD", "BUY", price="10", quantity=0)],
    )

    assert sheet["order_intents"][0]["delta_quantity"] > 0
    assert sheet["order_intents"][0]["blocking_status"] == "OK"


def test_missing_price_blocks_order_without_fake_quantity():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("EEE", "BUY", price="0", quantity=0)],
    )

    assert sheet["today_conclusion"] == "BLOCKED"
    order = sheet["order_intents"][0]
    assert order["blocking_status"] == "BLOCKED_PRICE_MISSING"
    assert order["delta_quantity"] == 0.0
    assert sheet["order_summary"]["blocked"] == 1


def test_wait_when_no_holdings_and_no_recommendations():
    sheet = _execute(_snapshot(holdings=[], baseline="empty_positions"), [])

    assert sheet["today_conclusion"] == "WAIT"
    assert sheet["order_summary"]["total"] == 0
    assert sheet["holdings"] == []
