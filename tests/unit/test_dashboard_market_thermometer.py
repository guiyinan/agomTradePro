"""Tests for dashboard market thermometer context wiring."""

from __future__ import annotations

from types import SimpleNamespace

from apps.dashboard.interface.dashboard_regime_context import _score_to_percent
from apps.dashboard.interface.views import (
    _build_action_recommendation_context,
    _build_attention_items_context,
    _build_browser_notification_context,
    _build_market_thermometer_context,
    _build_regime_status_context,
)


def test_build_market_thermometer_context_marks_personal_threshold_and_overheat():
    context = _build_market_thermometer_context(
        {
            "observed_at": "2026-05-19",
            "score": 82.0,
            "band": "overheat",
            "effective_band": "overheat",
            "threshold_source": "user_override",
            "change_5d": 7.0,
            "change_20d": 18.0,
            "components": [
                {"label": "成交额", "score": 90.0, "weight": 0.25},
                {"label": "融资余额", "score": 70.0, "weight": 0.2},
            ],
            "trigger_reasons": ["成交额抬升", "融资余额抬升"],
            "must_not_use_for_decision": False,
        }
    )

    assert context["market_temperature_is_overheat"] is True
    assert context["market_temperature_threshold_source"] == "user_override"
    assert context["market_temperature_top_reasons"] == ["成交额抬升", "融资余额抬升"]


def test_attention_items_include_market_thermometer_warning():
    data = SimpleNamespace(active_signals=[], position_count=1)
    context = _build_attention_items_context(
        data,
        navigator=None,
        pulse=None,
        market_thermometer={"effective_band": "extreme"},
    )

    assert any(item["meta"] == "来源: market_thermometer" for item in context["attention_items"])


def test_build_market_thermometer_context_hides_zero_score_when_snapshot_is_fully_missing():
    context = _build_market_thermometer_context(
        {
            "observed_at": "2026-05-22",
            "score": 0.0,
            "band": "cold",
            "effective_band": "cold",
            "score_available": False,
            "valid_component_count": 0,
            "must_not_use_for_decision": True,
            "blocked_reason": "有效组件数不足，当前仅 0 个，低于要求 4 个。",
        }
    )

    assert context["market_temperature_score"] is None
    assert context["market_temperature_score_available"] is False
    assert context["market_temperature_band_label"] == "数据缺失"


def test_build_market_thermometer_context_rejects_non_finite_and_malformed_values():
    context = _build_market_thermometer_context(
        {
            "score": float("nan"),
            "effective_band": "hot",
            "change_5d": "not-a-number",
            "components": [
                {"label": "invalid", "score": "bad", "weight": float("inf")},
                "not-a-component",
            ],
        }
    )

    assert context["market_temperature_score"] is None
    assert context["market_temperature_score_available"] is False
    assert context["market_temperature_band"] == "unavailable"
    assert context["market_temperature_change_5d"] is None
    assert context["market_temperature_components"] == [
        {"label": "invalid", "score": "bad", "weight": float("inf")}
    ]


def test_missing_macro_components_fail_closed():
    status = _build_regime_status_context(None, None, None)
    action = _build_action_recommendation_context(None)
    notification = _build_browser_notification_context(None, None)

    assert status["pulse_strength"] == "unavailable"
    assert status["risk_budget_pct"] is None
    assert status["action_blocked"] is True
    assert status["must_not_use_for_decision"] is True
    assert action["action_blocked"] is True
    assert action["action_blocked_code"] == "action_unavailable"
    assert action["action_risk_budget"] is None
    assert action["must_not_use_for_decision"] is True
    assert notification["browser_notification_enabled"] is False


def test_blocked_action_does_not_publish_executable_allocation():
    action = SimpleNamespace(
        must_not_use_for_decision=True,
        asset_weights={"equity": 0.8, "cash": 0.2},
        risk_budget_pct=0.8,
        position_limit_pct=0.1,
        recommended_sectors=["科技"],
        benefiting_styles=["成长"],
        hedge_recommendation=None,
        regime_contribution="regime",
        pulse_contribution="pulse",
        reasoning="data stale",
        confidence=0.9,
        blocked_reason="Pulse 数据过期",
        blocked_code="stale_pulse",
        stale_indicator_codes=["PMI"],
    )

    context = _build_action_recommendation_context(action)

    assert context["action_weights"] == {}
    assert context["action_risk_budget"] is None
    assert context["action_position_limit"] is None
    assert context["action_sectors"] == []
    assert context["action_styles"] == []
    assert context["action_hedge"] is None
    assert context["action_blocked"] is True
    assert context["must_not_use_for_decision"] is True


def test_score_to_percent_rejects_non_finite_values():
    assert _score_to_percent(float("nan")) == 0
    assert _score_to_percent(float("inf")) == 0
