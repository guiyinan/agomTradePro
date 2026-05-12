from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.decision_rhythm.domain.entities import (
    PortfolioTransitionPlan,
    TransitionOrder,
    TransitionPlanStatus,
)
from apps.decision_rhythm.infrastructure.models import PortfolioTransitionPlanModel
from apps.decision_rhythm.infrastructure.repositories import PortfolioTransitionPlanRepository


@pytest.mark.django_db
def test_transition_plan_repository_serializes_nested_json_snapshots():
    repository = PortfolioTransitionPlanRepository()
    snapshot_at = datetime(2026, 3, 29, 9, 30, tzinfo=UTC)
    review_at = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)

    plan = PortfolioTransitionPlan(
        plan_id="plan_repo_json",
        account_id="acct-repo-1",
        as_of=snapshot_at,
        source_recommendation_ids=["rec_repo_1"],
        current_positions_snapshot=[
            {
                "asset_code": "000001.SH",
                "market_value": Decimal("1100.00"),
                "snapshot_at": snapshot_at,
                "metrics": {
                    "avg_cost": Decimal("10.0000"),
                },
            }
        ],
        target_positions_snapshot=[
            {
                "asset_code": "000001.SH",
                "target_value": Decimal("50000.00"),
                "rebalanced_on": date(2026, 3, 29),
            }
        ],
        orders=[
            TransitionOrder(
                security_code="000001.SH",
                action="BUY",
                current_qty=100,
                target_qty=500,
                delta_qty=400,
                current_weight=0.01,
                target_weight=0.05,
                price_band_low=Decimal("10.50"),
                price_band_high=Decimal("11.00"),
                max_capital=Decimal("50000.00"),
                stop_loss_price=Decimal("9.50"),
                invalidation_rule={
                    "logic": "AND",
                    "conditions": [
                        {
                            "indicator_code": "PMI",
                            "threshold": Decimal("50.0"),
                        }
                    ],
                },
                source_recommendation_id="rec_repo_1",
                notes=["serialize"],
            )
        ],
        risk_contract={
            "review_at": review_at,
            "max_drawdown": Decimal("0.08"),
        },
        summary={
            "totals": {
                "target_capital": Decimal("50000.00"),
            }
        },
        status=TransitionPlanStatus.DRAFT,
    )

    saved_plan = repository.save(plan)
    model = PortfolioTransitionPlanModel.objects.get(plan_id="plan_repo_json")

    assert model.current_positions_snapshot[0]["market_value"] == "1100.00"
    assert model.current_positions_snapshot[0]["snapshot_at"] == "2026-03-29T09:30:00+00:00"
    assert model.current_positions_snapshot[0]["metrics"]["avg_cost"] == "10.0000"
    assert model.target_positions_snapshot[0]["target_value"] == "50000.00"
    assert model.target_positions_snapshot[0]["rebalanced_on"] == "2026-03-29"
    assert model.orders[0]["invalidation_rule"]["conditions"][0]["threshold"] == "50.0"
    assert model.risk_contract["review_at"] == "2026-03-29T10:00:00+00:00"
    assert model.risk_contract["max_drawdown"] == "0.08"
    assert model.summary["totals"]["target_capital"] == "50000.00"
    assert saved_plan.current_positions_snapshot[0]["market_value"] == "1100.00"
    assert saved_plan.target_positions_snapshot[0]["rebalanced_on"] == "2026-03-29"
