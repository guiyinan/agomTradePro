from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.decision_rhythm.application.today_queue import TodayDecisionQueueQueryService
from apps.decision_rhythm.domain.entities import (
    ApprovalStatus,
    RecommendationStatus,
    TransitionPlanStatus,
    UserDecisionAction,
)

User = get_user_model()
DecisionFeatureSnapshotModel = apps.get_model("decision_rhythm", "DecisionFeatureSnapshotModel")
ExecutionApprovalRequestModel = apps.get_model(
    "decision_rhythm",
    "ExecutionApprovalRequestModel",
)
PortfolioTransitionPlanModel = apps.get_model(
    "decision_rhythm",
    "PortfolioTransitionPlanModel",
)
SimulatedAccountModel = apps.get_model("simulated_trading", "SimulatedAccountModel")
UnifiedRecommendationModel = apps.get_model("decision_rhythm", "UnifiedRecommendationModel")


@pytest.fixture(autouse=True)
def disable_today_queue_health_items(monkeypatch):
    monkeypatch.setattr(
        TodayDecisionQueueQueryService,
        "_system_health_items",
        lambda self, account_id: [],
    )


def _feature_snapshot(snapshot_id: str, security_code: str):
    return DecisionFeatureSnapshotModel.objects.create(
        snapshot_id=snapshot_id,
        security_code=security_code,
        snapshot_time=timezone.now(),
        regime="Recovery",
        regime_confidence=0.8,
        policy_level="MEDIUM",
        beta_gate_passed=True,
    )


def _recommendation(
    *,
    recommendation_id: str,
    account_id: str = "default",
    security_code: str = "000001.SH",
    status: str = RecommendationStatus.NEW.value,
    user_action: str = UserDecisionAction.PENDING.value,
):
    snapshot = _feature_snapshot(f"snapshot_{recommendation_id}", security_code)
    return UnifiedRecommendationModel.objects.create(
        recommendation_id=recommendation_id,
        account_id=account_id,
        security_code=security_code,
        side="BUY",
        regime="Recovery",
        regime_confidence=0.8,
        policy_level="MEDIUM",
        beta_gate_passed=True,
        composite_score=0.78,
        confidence=0.82,
        fair_value=Decimal("12.50"),
        entry_price_low=Decimal("10.50"),
        entry_price_high=Decimal("11.00"),
        target_price_low=Decimal("13.00"),
        target_price_high=Decimal("14.50"),
        stop_loss_price=Decimal("9.50"),
        position_pct=5.0,
        suggested_quantity=500,
        max_capital=Decimal("50000"),
        source_signal_ids=[],
        source_candidate_ids=["alpha_rank:000001.SH"],
        feature_snapshot=snapshot,
        status=status,
        user_action=user_action,
    )


def _blocking_plan(*, account_id: str = "default"):
    return PortfolioTransitionPlanModel.objects.create(
        plan_id="plan_blocking_today",
        account_id=account_id,
        source_recommendation_ids=["rec_adopted"],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[
            {
                "security_code": "000001.SH",
                "action": "BUY",
                "current_qty": 0,
                "target_qty": 500,
                "delta_qty": 500,
                "current_weight": 0.0,
                "target_weight": 5.0,
                "price_band_low": "10.50",
                "price_band_high": "11.00",
                "max_capital": "50000",
                "stop_loss_price": None,
                "invalidation_rule": {
                    "logic": "AND",
                    "conditions": [],
                    "requires_user_confirmation": True,
                },
                "source_recommendation_id": "rec_adopted",
            }
        ],
        risk_contract={},
        summary={"orders_count": 1},
        status=TransitionPlanStatus.DRAFT.value,
        as_of=timezone.now(),
    )


def _pending_approval(plan, *, account_id: str = "default"):
    return ExecutionApprovalRequestModel.objects.create(
        request_id="apr_pending_today",
        account_id=account_id,
        security_code="000001.SH",
        side="BUY",
        approval_status=ApprovalStatus.PENDING.value,
        suggested_quantity=500,
        market_price_at_review=Decimal("10.80"),
        price_range_low=Decimal("10.50"),
        price_range_high=Decimal("11.00"),
        stop_loss_price=Decimal("9.50"),
        risk_check_results={"plan_validation": {"passed": True}},
        reviewer_comments="",
        regime_source="Recovery",
        transition_plan=plan,
        execution_params_json={},
    )


def _account(user, name: str):
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("100000"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100000"),
        is_active=True,
        auto_trading_enabled=True,
    )


@pytest.mark.django_db
def test_today_queue_rejects_unauthenticated_user():
    client = Client()

    response = client.get("/api/decision/workspace/today-queue/")

    assert response.status_code in {302, 403}


@pytest.mark.django_db
def test_today_queue_returns_empty_items_for_authenticated_user():
    user = User.objects.create_user(username="today_queue_empty", password="x")
    client = Client()
    client.force_login(user)

    response = client.get("/api/decision/workspace/today-queue/?account_id=default")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.django_db
def test_today_queue_allows_only_owned_numeric_account():
    user = User.objects.create_user(username="today_queue_owner", password="x")
    other_user = User.objects.create_user(username="today_queue_other", password="x")
    owned_account = _account(user, "Owned Account")
    foreign_account = _account(other_user, "Foreign Account")
    _recommendation(
        recommendation_id="rec_owned_account",
        account_id=str(owned_account.id),
        user_action=UserDecisionAction.ADOPTED.value,
    )
    client = Client()
    client.force_login(user)

    owned_response = client.get(
        f"/api/decision/workspace/today-queue/?account_id={owned_account.id}"
    )
    foreign_response = client.get(
        f"/api/decision/workspace/today-queue/?account_id={foreign_account.id}"
    )

    assert owned_response.status_code == 200
    assert owned_response.json()["total"] == 1
    assert foreign_response.status_code == 403


@pytest.mark.django_db
def test_today_queue_includes_adopted_conflict_blocking_plan_and_pending_approval():
    user = User.objects.create_user(username="today_queue_user", password="x")
    client = Client()
    client.force_login(user)

    _recommendation(
        recommendation_id="rec_adopted",
        user_action=UserDecisionAction.ADOPTED.value,
    )
    _recommendation(
        recommendation_id="rec_conflict",
        security_code="600519.SH",
        status=RecommendationStatus.CONFLICT.value,
        user_action=UserDecisionAction.PENDING.value,
    )
    plan = _blocking_plan()
    _pending_approval(plan)

    response = client.get("/api/decision/workspace/today-queue/?account_id=default")

    assert response.status_code == 200
    items = response.json()["items"]
    item_types = {item["type"] for item in items}
    assert "recommendation_adopted" in item_types
    assert "recommendation_conflict" in item_types
    assert "transition_plan_blocking" in item_types
    assert "execution_approval_pending" in item_types
    assert next(
        item for item in items if item["type"] == "recommendation_adopted"
    )["next_action"] == "生成计划"
    assert next(
        item for item in items if item["type"] == "recommendation_conflict"
    )["next_action"] == "处理冲突"
    assert next(
        item for item in items if item["type"] == "transition_plan_blocking"
    )["next_action"] == "补齐风控/证伪"
    assert next(
        item for item in items if item["type"] == "execution_approval_pending"
    )["next_action"] == "审批执行"
