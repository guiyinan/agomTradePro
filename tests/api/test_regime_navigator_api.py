from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from apps.regime.domain.entities import (
    AssetWeightRange,
    RegimeAssetGuidance,
    RegimeMovement,
    RegimeNavigatorOutput,
    WatchIndicator,
)


@pytest.mark.django_db
def test_regime_navigator_api_contract(monkeypatch):
    user = User.objects.create_user(username="nav-api", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    navigator = RegimeNavigatorOutput(
        regime_name="Recovery",
        confidence=0.61,
        distribution={"Recovery": 0.61, "Overheat": 0.2, "Deflation": 0.1, "Stagflation": 0.09},
        movement=RegimeMovement(
            direction="transitioning",
            transition_target="Overheat",
            transition_probability=0.35,
            leading_indicators=["CPI 强势上行"],
            momentum_summary="PMI 上升 + CPI 上升",
        ),
        asset_guidance=RegimeAssetGuidance(
            weight_ranges=[
                AssetWeightRange("equity", 0.5, 0.7, "权益类"),
                AssetWeightRange("bond", 0.15, 0.3, "债券类"),
            ],
            risk_budget_pct=0.85,
            recommended_sectors=["消费", "科技"],
            benefiting_styles=["成长"],
            reasoning="复苏期保持权益占优。",
        ),
        watch_indicators=[WatchIndicator("PMI", "制造业PMI", "跌破50", "high")],
        generated_at=date(2026, 3, 24),
        data_freshness="fresh",
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, as_of_date=None: navigator,
    )

    response = client.get("/api/regime/navigator/")

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["regime_name"] == "Recovery"
    assert payload["data"]["movement"]["transition_target"] == "Overheat"
    assert "asset_guidance" in payload["data"]
    assert "watch_indicators" in payload["data"]
