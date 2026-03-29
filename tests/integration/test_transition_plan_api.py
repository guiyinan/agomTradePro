from decimal import Decimal

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
PulseLog = apps.get_model("pulse", "PulseLog")


@pytest.mark.django_db
def test_transition_plan_generate_update_and_preview_flow():
    user = User.objects.create_user(username="plan_api_user", password="x")
    client = Client()
    client.force_login(user)

    DecisionQuotaModel.objects.create(
        quota_id="plan_api_quota",
        period=QuotaPeriod.WEEKLY.value,
        max_decisions=100,
        used_decisions=0,
        max_execution_count=50,
        used_executions=0,
    )

    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Plan API Account",
        account_type="simulated",
        initial_capital=Decimal("100000"),
        current_cash=Decimal("100000"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100000"),
        is_active=True,
        auto_trading_enabled=True,
    )

    snapshot = DecisionFeatureSnapshotModel.objects.create(
        snapshot_id="plan_api_snapshot",
        security_code="000001.SH",
        snapshot_time=timezone.now(),
        regime="REGIME_1",
        regime_confidence=0.8,
        policy_level="MEDIUM",
        beta_gate_passed=True,
    )

    recommendation = UnifiedRecommendationModel.objects.create(
        recommendation_id="plan_api_rec",
        account_id=str(account.id),
        security_code="000001.SH",
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
        feature_snapshot=snapshot,
        status="NEW",
        user_action=UserDecisionAction.ADOPTED.value,
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
