from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient

from apps.pulse.domain.entities import DimensionScore, PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.repositories import PulseRepository
from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase
from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.regime.domain.entities import (
    AssetWeightRange,
    RegimeAssetGuidance,
    RegimeMovement,
    RegimeNavigatorOutput,
    WatchIndicator,
)


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_html_partial_contract(response, *fragments: str) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in fragments:
        assert fragment in content
    return content


def _sample_pulse_snapshot() -> PulseSnapshot:
    return PulseSnapshot(
        observed_at=date(2026, 3, 24),
        regime_context="Recovery",
        dimension_scores=[
            DimensionScore("growth", 0.5, "bullish", 2, "增长脉搏偏强"),
            DimensionScore("inflation", 0.1, "neutral", 1, "通胀脉搏中性"),
            DimensionScore("liquidity", -0.4, "bearish", 2, "流动性脉搏偏弱"),
            DimensionScore("sentiment", 0.2, "neutral", 2, "情绪脉搏中性"),
        ],
        composite_score=0.1,
        regime_strength="moderate",
        transition_warning=True,
        transition_direction="Deflation",
        transition_reasons=["增长和流动性同步走弱"],
        indicator_readings=[
            PulseIndicatorReading(
                code="CN_TERM_SPREAD_10Y2Y",
                name="国债利差(10Y-2Y)",
                dimension="growth",
                value=85.0,
                z_score=0.6,
                direction="improving",
                signal="bullish",
                signal_score=0.5,
                weight=1.0,
                data_age_days=1,
                is_stale=False,
            )
        ],
        data_source="calculated",
        stale_indicator_count=0,
    )


def _sample_navigator() -> RegimeNavigatorOutput:
    return RegimeNavigatorOutput(
        regime_name="Recovery",
        confidence=0.62,
        distribution={"Recovery": 0.62, "Overheat": 0.18, "Deflation": 0.12, "Stagflation": 0.08},
        movement=RegimeMovement(
            direction="transitioning",
            transition_target="Deflation",
            transition_probability=0.3,
            leading_indicators=["PMI 动量下降"],
            momentum_summary="PMI 下降 + CPI 持平",
        ),
        asset_guidance=RegimeAssetGuidance(
            weight_ranges=[
                AssetWeightRange("equity", 0.5, 0.7, "权益类"),
                AssetWeightRange("bond", 0.15, 0.3, "债券类"),
                AssetWeightRange("commodity", 0.05, 0.15, "商品类"),
                AssetWeightRange("cash", 0.05, 0.15, "现金类"),
            ],
            risk_budget_pct=0.85,
            recommended_sectors=["消费", "科技"],
            benefiting_styles=["成长"],
            reasoning="复苏期建议保持权益占优。",
        ),
        watch_indicators=[
            WatchIndicator("PMI", "制造业PMI", "跌破50", "high"),
            WatchIndicator("CPI", "居民消费价格指数", "> 2%", "high"),
        ],
        generated_at=date(2026, 3, 24),
        data_freshness="fresh",
    )


def _sample_action() -> RegimeActionRecommendation:
    return RegimeActionRecommendation(
        asset_weights={"equity": 0.55, "bond": 0.25, "commodity": 0.1, "cash": 0.1},
        risk_budget_pct=0.72,
        position_limit_pct=0.1,
        recommended_sectors=["消费", "科技"],
        benefiting_styles=["成长"],
        hedge_recommendation=None,
        reasoning="复苏偏弱，适度保留防御仓位。",
        regime_contribution="Recovery期，权益区间 50-70%",
        pulse_contribution="脉搏moderate(score=0.10)，插值系数0.55",
        generated_at=date(2026, 3, 24),
        confidence=0.58,
    )


@pytest.mark.django_db
def test_regime_pulse_phase1_endpoints_and_dashboard_partials(monkeypatch):
    pulse = _sample_pulse_snapshot()
    PulseRepository().save_snapshot(pulse)

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, as_of_date=None: _sample_navigator(),
    )
    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.GetActionRecommendationUseCase.execute",
        lambda self, as_of_date=None: _sample_action(),
    )
    monkeypatch.setattr(
        "apps.dashboard.interface.views._build_dashboard_data",
        lambda user_id: SimpleNamespace(
            active_signals=[{"asset_code": "000001.SH"}],
            position_count=2,
            positions=[],
            invested_value=100.0,
        ),
    )
    monkeypatch.setattr(
        "apps.dashboard.interface.views._ensure_dashboard_positions",
        lambda data, user_id: data,
    )

    user = User.objects.create_user(username="phase1", password="pass")
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    html_client = Client()
    html_client.force_login(user)

    pulse_response = api_client.get("/api/pulse/current/")
    assert pulse_response.status_code == 200
    assert pulse_response["Content-Type"].startswith("application/json")
    pulse_payload = pulse_response.json()
    assert pulse_payload["success"] is True
    assert pulse_payload["data"]["regime_strength"] == "moderate"

    navigator_response = api_client.get("/api/regime/navigator/")
    assert navigator_response.status_code == 200
    assert navigator_response["Content-Type"].startswith("application/json")
    navigator_payload = navigator_response.json()
    assert navigator_payload["success"] is True
    assert navigator_payload["data"]["regime_name"] == "Recovery"

    action_response = api_client.get("/api/regime/action/")
    assert action_response.status_code == 200
    assert action_response["Content-Type"].startswith("application/json")
    action_payload = action_response.json()
    assert action_payload["success"] is True
    assert abs(sum(action_payload["data"]["asset_weights"].values()) - 1.0) < 0.01

    attention_html = html_client.get("/api/dashboard/attention-items/", HTTP_HX_REQUEST="true")
    _assert_html_partial_contract(
        attention_html,
        'id="attentionItemsCard"',
        "今日关注",
        "信号待跟进",
        "attention-card__count",
        "attention-item__title",
        "hx-get=\"/api/dashboard/attention-items/\"",
    )

    status_html = html_client.get("/api/dashboard/regime-status/", HTTP_HX_REQUEST="true")
    status_content = _assert_html_partial_contract(
        status_html,
        'id="regimeStatusBar"',
        "复苏期",
        "转向 Deflation",
        "置信度",
        "脉搏:",
        "风险预算",
        "转折预警",
        "hx-get=\"/api/dashboard/regime-status/\"",
    )
    assert "加载中..." not in status_content


@pytest.mark.django_db
def test_action_recommendation_blocks_unreliable_pulse(monkeypatch):
    captured_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "apps.regime.application.navigator_use_cases.BuildRegimeNavigatorUseCase.execute",
        lambda self, as_of_date=None: _sample_navigator(),
    )

    def _fake_execute(self, *args, **kwargs):
        captured_calls.append(dict(kwargs))
        if kwargs.get("require_reliable"):
            return None
        return _sample_pulse_snapshot()

    monkeypatch.setattr(
        "apps.pulse.application.use_cases.GetLatestPulseUseCase.execute",
        _fake_execute,
    )

    action = GetActionRecommendationUseCase().execute(date(2026, 4, 8))

    assert action is not None
    assert any(call.get("require_reliable") is True for call in captured_calls)
    assert any(call.get("refresh_if_stale") is True for call in captured_calls)
    assert any(call.get("require_reliable") is False for call in captured_calls)
    assert action.must_not_use_for_decision is True
    assert action.blocked_code == "pulse_unreliable"
    assert "已阻断" in action.blocked_reason
