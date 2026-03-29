from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.decision_rhythm.domain.entities import QuotaPeriod, UserDecisionAction

User = get_user_model()
DecisionQuotaModel = apps.get_model("decision_rhythm", "DecisionQuotaModel")
DecisionFeatureSnapshotModel = apps.get_model("decision_rhythm", "DecisionFeatureSnapshotModel")
UnifiedRecommendationModel = apps.get_model("decision_rhythm", "UnifiedRecommendationModel")
SimulatedAccountModel = apps.get_model("simulated_trading", "SimulatedAccountModel")
PositionModel = apps.get_model("simulated_trading", "PositionModel")
PulseLog = apps.get_model("pulse", "PulseLog")
StockInfoModel = apps.get_model("equity", "StockInfoModel")


def _create_workspace_quota(quota_id: str) -> None:
    DecisionQuotaModel.objects.create(
        quota_id=quota_id,
        period=QuotaPeriod.WEEKLY.value,
        max_decisions=100,
        used_decisions=0,
        max_execution_count=50,
        used_executions=0,
    )


def _create_simulated_account(user: Any, account_name: str) -> Any:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=account_name,
        account_type="simulated",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("100000"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100000"),
        is_active=True,
        auto_trading_enabled=True,
    )


def _create_feature_snapshot(snapshot_id: str, security_code: str) -> Any:
    return DecisionFeatureSnapshotModel.objects.create(
        snapshot_id=snapshot_id,
        security_code=security_code,
        snapshot_time=timezone.now(),
        regime="REGIME_1",
        regime_confidence=0.8,
        policy_level="MEDIUM",
        beta_gate_passed=True,
    )


def _create_stock_info(security_code: str, security_name: str) -> None:
    StockInfoModel.objects.create(
        stock_code=security_code,
        name=security_name,
        sector="银行",
        market="SH",
        list_date=timezone.now().date(),
        is_active=True,
    )


def _create_recommendation(
    *,
    recommendation_id: str,
    account_id: str,
    security_code: str,
    feature_snapshot: Any,
    user_action: str,
) -> Any:
    return UnifiedRecommendationModel.objects.create(
        recommendation_id=recommendation_id,
        account_id=account_id,
        security_code=security_code,
        side="BUY",
        regime="REGIME_1",
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
        source_candidate_ids=["cand1"],
        feature_snapshot=feature_snapshot,
        status="NEW",
        user_action=user_action,
    )


@pytest.mark.django_db
def test_transition_plan_generate_update_and_preview_flow():
    user = User.objects.create_user(username="plan_api_user", password="x")
    client = Client()
    client.force_login(user)

    _create_workspace_quota("plan_api_quota")
    account = _create_simulated_account(user, "Plan API Account")
    snapshot = _create_feature_snapshot("plan_api_snapshot", "000001.SH")
    _create_stock_info("000001.SH", "平安银行")
    recommendation = _create_recommendation(
        recommendation_id="plan_api_rec",
        account_id=str(account.id),
        security_code="000001.SH",
        feature_snapshot=snapshot,
        user_action=UserDecisionAction.ADOPTED.value,
    )

    PositionModel.objects.create(
        account=account,
        asset_code="000001.SH",
        asset_name="Ping An Bank",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("11.0000"),
        market_value=Decimal("1100.00"),
        unrealized_pnl=Decimal("100.00"),
        unrealized_pnl_pct=10.0,
        first_buy_date=timezone.now().date(),
    )

    generate_response = client.post(
        "/api/decision/workspace/plans/generate/",
        data={"account_id": str(account.id)},
        content_type="application/json",
    )
    assert generate_response.status_code == 201
    generate_payload = generate_response.json()["data"]
    assert generate_payload["plan_id"]
    assert generate_payload["orders"][0]["source_recommendation_id"] == recommendation.recommendation_id
    assert generate_payload["can_enter_approval"] is False
    assert generate_payload["current_positions"][0]["asset_code"] == "000001.SH"
    assert generate_payload["current_positions"][0]["security_name"] == "Ping An Bank"
    assert str(generate_payload["current_positions"][0]["market_value"]) == "1100.00"
    assert generate_payload["target_positions"][0]["security_name"] == "平安银行"
    assert generate_payload["orders"][0]["security_name"] == "平安银行"

    update_response = client.post(
        f"/api/decision/workspace/plans/{generate_payload['plan_id']}/update/",
        data={
            "orders": [
                {
                    "source_recommendation_id": recommendation.recommendation_id,
                    "security_code": "000001.SH",
                    "stop_loss_price": "9.50",
                    "review_by": "2026-03-31",
                    "invalidation_rule": {
                        "logic": "AND",
                        "conditions": [
                            {
                                "indicator_code": "PMI",
                                "operator": "<",
                                "threshold": 50,
                            }
                        ],
                    },
                }
            ]
        },
        content_type="application/json",
    )
    assert update_response.status_code == 200
    updated_payload = update_response.json()["data"]
    assert updated_payload["can_enter_approval"] is True
    assert updated_payload["status"] == "READY_FOR_APPROVAL"

    preview_response = client.post(
        "/api/decision/execute/preview/",
        data={"account_id": str(account.id), "plan_id": generate_payload["plan_id"]},
        content_type="application/json",
    )
    assert preview_response.status_code == 201
    preview_payload = preview_response.json()["data"]
    assert preview_payload["plan_id"] == generate_payload["plan_id"]
    assert preview_payload["recommendation_type"] == "plan"
    assert preview_payload["request_id"]


@pytest.mark.django_db
def test_transition_plan_generate_with_explicit_recommendation_ids_uses_selected_recommendations():
    user = User.objects.create_user(username="plan_api_selected_user", password="x")
    client = Client()
    client.force_login(user)

    _create_workspace_quota("plan_selected_quota")
    account = _create_simulated_account(user, "Plan Selected Account")

    adopted_snapshot = _create_feature_snapshot("plan_selected_snapshot_1", "000001.SH")
    selected_snapshot = _create_feature_snapshot("plan_selected_snapshot_2", "600519.SH")
    _create_stock_info("000001.SH", "平安银行")
    _create_stock_info("600519.SH", "贵州茅台")

    _create_recommendation(
        recommendation_id="plan_selected_default_rec",
        account_id=str(account.id),
        security_code="000001.SH",
        feature_snapshot=adopted_snapshot,
        user_action=UserDecisionAction.ADOPTED.value,
    )
    selected_recommendation = _create_recommendation(
        recommendation_id="plan_selected_explicit_rec",
        account_id=str(account.id),
        security_code="600519.SH",
        feature_snapshot=selected_snapshot,
        user_action=UserDecisionAction.IGNORED.value,
    )

    generate_response = client.post(
        "/api/decision/workspace/plans/generate/",
        data={
            "account_id": str(account.id),
            "recommendation_ids": [selected_recommendation.recommendation_id],
        },
        content_type="application/json",
    )

    assert generate_response.status_code == 201
    generate_payload = generate_response.json()["data"]
    assert generate_payload["source_recommendation_ids"] == [selected_recommendation.recommendation_id]
    assert generate_payload["current_positions"] == []
    assert [item["security_code"] for item in generate_payload["target_positions"]] == ["600519.SH"]
    assert [item["security_code"] for item in generate_payload["orders"]] == ["600519.SH"]
    assert generate_payload["target_positions"][0]["security_name"] == "贵州茅台"
    assert generate_payload["orders"][0]["security_name"] == "贵州茅台"


@pytest.mark.django_db
def test_invalidation_template_and_ai_draft_endpoints(monkeypatch):
    user = User.objects.create_user(username="plan_invalidation_user", password="x")
    client = Client()
    client.force_login(user)

    PulseLog.objects.create(
        observed_at=timezone.now().date(),
        regime_context="RECOVERY",
        growth_score=0.4,
        inflation_score=0.1,
        liquidity_score=0.2,
        sentiment_score=0.3,
        composite_score=0.35,
        regime_strength="strong",
        transition_warning=True,
        transition_direction="down",
        indicator_readings={},
        transition_reasons=["liquidity softening"],
    )

    template_response = client.post(
        "/api/decision/workspace/invalidation/template/",
        data={
            "security_code": "000001.SH",
            "side": "BUY",
            "rationale": "依赖宏观修复持续和脉搏维持强势",
        },
        content_type="application/json",
    )
    assert template_response.status_code == 200
    template_payload = template_response.json()["data"]
    assert template_payload["template"]["conditions"][0]["indicator_code"] == "PULSE_COMPOSITE"
    assert template_payload["pulse_context"]["transition_warning"] is True

    class DummyClient:
        def chat_completion(self, messages, temperature=0.2, max_tokens=500):
            return {
                "status": "success",
                "content": """
                {
                  "logic": "AND",
                  "conditions": [
                    {
                      "indicator_code": "PULSE_COMPOSITE",
                      "indicator_type": "pulse",
                      "operator": "<",
                      "threshold": 0.1
                    }
                  ],
                  "requires_user_confirmation": false,
                  "description": "AI draft"
                }
                """,
                "provider_used": "test-provider",
                "model": "test-model",
            }

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.api_views.AIClientFactory.get_client",
        lambda self: DummyClient(),
    )

    ai_response = client.post(
        "/api/decision/workspace/invalidation/ai-draft/",
        data={
            "security_code": "000001.SH",
            "side": "BUY",
            "rationale": "依赖宏观修复持续和脉搏维持强势",
            "user_prompt": "把 Pulse 和 Regime 都写进去",
            "existing_rule": {},
        },
        content_type="application/json",
    )
    assert ai_response.status_code == 200
    ai_payload = ai_response.json()["data"]
    assert ai_payload["draft"]["conditions"][0]["indicator_code"] == "PULSE_COMPOSITE"
    assert ai_payload["provider_used"] == "test-provider"
