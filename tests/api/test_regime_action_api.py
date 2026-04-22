from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from apps.regime.domain.action_mapper import RegimeActionRecommendation


@pytest.mark.django_db
def test_regime_action_api_contract(monkeypatch):
    user = User.objects.create_user(username="action-api", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    action = RegimeActionRecommendation(
        asset_weights={"equity": 0.56, "bond": 0.24, "commodity": 0.1, "cash": 0.1},
        risk_budget_pct=0.74,
        position_limit_pct=0.1,
        recommended_sectors=["消费", "科技"],
        benefiting_styles=["成长"],
        hedge_recommendation=None,
        reasoning="复苏偏弱，适度降杠杆。",
        regime_contribution="Recovery期，权益区间 50-70%",
        pulse_contribution="脉搏moderate(score=0.12)，插值系数0.56",
        generated_at=date(2026, 3, 24),
        confidence=0.63,
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.GetActionRecommendationUseCase.execute",
        lambda self, as_of_date=None: action,
    )

    response = client.get("/api/regime/action/")

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["asset_weights"]["equity"] == 0.56
    assert "risk_budget_pct" in payload["data"]
    assert "regime_contribution" in payload["data"]
    assert payload["data"]["must_not_use_for_decision"] is False
    assert payload["data"]["contract"]["must_not_use_for_decision"] is False


@pytest.mark.django_db
def test_regime_action_api_returns_blocked_contract_for_unreliable_pulse(monkeypatch):
    user = User.objects.create_user(username="action-api-blocked", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    blocked = RegimeActionRecommendation(
        asset_weights={},
        risk_budget_pct=0.0,
        position_limit_pct=0.0,
        recommended_sectors=[],
        benefiting_styles=[],
        hedge_recommendation=None,
        reasoning="Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
        regime_contribution="Recovery 导航仪仍可读取，但 Pulse 数据未达到决策级可靠性。",
        pulse_contribution="Pulse 数据不可靠，联合行动建议已阻断。",
        generated_at=date(2026, 4, 21),
        confidence=0.41,
        must_not_use_for_decision=True,
        blocked_reason="Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
        blocked_code="pulse_unreliable",
        pulse_observed_at=date(2026, 4, 20),
        pulse_is_reliable=False,
        stale_indicator_codes=["CN_PMI", "000300.SH"],
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.GetActionRecommendationUseCase.execute",
        lambda self, as_of_date=None: blocked,
    )

    response = client.get("/api/regime/action/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["must_not_use_for_decision"] is True
    assert payload["data"]["blocked_code"] == "pulse_unreliable"
    assert payload["data"]["stale_indicator_codes"] == ["CN_PMI", "000300.SH"]
    assert payload["data"]["contract"]["pulse_is_reliable"] is False
