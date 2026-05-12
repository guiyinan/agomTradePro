from datetime import UTC, datetime
from decimal import Decimal

from apps.decision_rhythm.domain.entities import (
    RecommendationStatus,
    UnifiedRecommendation,
    UserDecisionAction,
    create_portfolio_transition_plan,
)


def _make_recommendation(
    recommendation_id: str,
    security_code: str,
    side: str,
    *,
    suggested_quantity: int = 500,
    source_signal_ids: list[str] | None = None,
) -> UnifiedRecommendation:
    now = datetime.now(UTC)
    return UnifiedRecommendation(
        recommendation_id=recommendation_id,
        account_id="acct-1",
        security_code=security_code,
        side=side,
        confidence=0.8,
        composite_score=0.75,
        fair_value=Decimal("12.5"),
        entry_price_low=Decimal("10.5"),
        entry_price_high=Decimal("11.0"),
        target_price_low=Decimal("13.0"),
        target_price_high=Decimal("14.0"),
        stop_loss_price=Decimal("9.5"),
        position_pct=8.0,
        suggested_quantity=suggested_quantity,
        max_capital=Decimal("50000"),
        source_signal_ids=source_signal_ids or [],
        source_candidate_ids=[],
        feature_snapshot_id="fsn_1",
        status=RecommendationStatus.NEW,
        user_action=UserDecisionAction.ADOPTED,
        user_action_note="",
        user_action_at=now,
        created_at=now,
        updated_at=now,
    )


def test_create_transition_plan_generates_buy_order_for_new_position():
    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[
            _make_recommendation("rec-buy", "000001.SH", "BUY", source_signal_ids=["1"])
        ],
        current_positions=[],
        signal_payloads={
            "1": {
                "invalidation_rule_json": {
                    "logic": "AND",
                    "conditions": [{"indicator_code": "PMI", "operator": "<", "threshold": 50}],
                },
                "invalidation_description": "PMI 跌破 50",
            }
        },
    )

    assert plan.can_enter_approval is True
    assert plan.status.value == "READY_FOR_APPROVAL"
    assert len(plan.orders) == 1
    order = plan.orders[0]
    assert order.action == "BUY"
    assert order.current_qty == 0
    assert order.target_qty == 500
    assert order.delta_qty == 500


def test_create_transition_plan_filters_sell_when_no_position_exists():
    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[_make_recommendation("rec-sell", "000002.SH", "SELL")],
        current_positions=[],
        signal_payloads={},
    )

    assert plan.orders == []
    assert plan.summary["filtered_out"][0]["reason"] == "no_position_to_sell"


def test_create_transition_plan_blocks_approval_when_invalidation_missing():
    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[_make_recommendation("rec-exit", "000003.SH", "SELL", suggested_quantity=300)],
        current_positions=[
            {
                "asset_code": "000003.SH",
                "asset_name": "Test",
                "quantity": 300,
                "avg_cost": "9.80",
                "current_price": "10.10",
                "market_value": "3030",
            }
        ],
        signal_payloads={},
    )

    assert len(plan.orders) == 1
    order = plan.orders[0]
    assert order.action == "EXIT"
    assert plan.can_enter_approval is False
    assert "缺少完整证伪条件" in plan.blocking_issues[0]


def test_create_transition_plan_blocks_approval_when_stop_loss_missing():
    recommendation = _make_recommendation("rec-buy-no-stop", "000004.SH", "BUY", source_signal_ids=["1"])
    recommendation.stop_loss_price = Decimal("0")

    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[recommendation],
        current_positions=[],
        signal_payloads={
            "1": {
                "invalidation_rule_json": {
                    "logic": "AND",
                    "conditions": [{"indicator_code": "PMI", "operator": "<", "threshold": 50}],
                },
                "invalidation_description": "PMI 跌破 50",
            }
        },
    )

    assert len(plan.orders) == 1
    assert plan.orders[0].action == "BUY"
    assert plan.can_enter_approval is False
    assert "缺少止损价" in plan.blocking_issues[0]


def test_create_transition_plan_converts_hold_target_to_reduce():
    recommendation = _make_recommendation("rec-reduce", "000005.SH", "HOLD", suggested_quantity=200)

    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[recommendation],
        current_positions=[
            {
                "asset_code": "000005.SH",
                "asset_name": "Test",
                "quantity": 500,
                "avg_cost": "10.00",
                "current_price": "10.50",
                "market_value": "5250",
            }
        ],
        signal_payloads={},
    )

    assert len(plan.orders) == 1
    order = plan.orders[0]
    assert order.action == "REDUCE"
    assert order.current_qty == 500
    assert order.target_qty == 200
    assert order.delta_qty == -300
    assert "reduce_from_hold_target" in order.notes


def test_create_transition_plan_blocks_hold_only_plans_from_approval():
    plan = create_portfolio_transition_plan(
        account_id="acct-1",
        recommendations=[_make_recommendation("rec-hold", "000001.SH", "BUY", suggested_quantity=100)],
        current_positions=[
            {
                "asset_code": "000001.SH",
                "asset_name": "Test",
                "quantity": 100,
                "avg_cost": "10.00",
                "current_price": "10.50",
                "market_value": "1050",
            }
        ],
        signal_payloads={},
    )

    assert len(plan.orders) == 1
    assert plan.orders[0].action == "HOLD"
    assert plan.orders[0].is_ready_for_approval is False
    assert plan.can_enter_approval is False
    assert plan.status.value == "DRAFT"
    assert plan.blocking_issues == ["当前计划没有可执行订单"]
