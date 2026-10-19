"""Tests for dashboard market thermometer context wiring."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.template.loader import render_to_string

from apps.dashboard.interface import dashboard_regime_context
from apps.dashboard.interface.dashboard_regime_context import (
    _load_market_thermometer_payload,
    _score_to_percent,
)
from apps.dashboard.interface.views import (
    _build_action_recommendation_context,
    _build_attention_items_context,
    _build_browser_notification_context,
    _build_market_thermometer_context,
    _build_regime_status_context,
)
from core.exceptions import DataFetchError


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


def test_load_market_thermometer_payload_returns_success_payload_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_payload: dict[str, Any] = {"score": 82.0, "observed_at": "2026-05-19"}

    def return_payload(
        *,
        user_id: int | None,
        use_personal_thresholds: bool,
    ) -> dict[str, Any]:
        assert user_id == 17
        assert use_personal_thresholds is True
        return expected_payload

    monkeypatch.setattr(
        dashboard_regime_context.data_center_interface_services,
        "load_market_thermometer_payload",
        return_payload,
    )

    assert _load_market_thermometer_payload(user_id=17) == expected_payload


def test_market_thermometer_calendar_unavailable_renders_blocked_without_score_or_source_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_calendar_unavailable(
        *,
        user_id: int | None,
        use_personal_thresholds: bool,
    ) -> dict[str, Any]:
        raise DataFetchError(
            "Exchange trading calendar is unavailable",
            code="MARKET_CALENDAR_UNAVAILABLE",
        )

    monkeypatch.setattr(
        dashboard_regime_context.data_center_interface_services,
        "load_market_thermometer_payload",
        raise_calendar_unavailable,
    )

    payload = _load_market_thermometer_payload(user_id=17)
    context = _build_market_thermometer_context(payload)
    rendered = render_to_string("components/market_thermometer_card.html", context)
    normalized = " ".join(rendered.split())

    assert payload["status"] == "blocked"
    assert payload["score"] is None
    assert payload["score_available"] is False
    assert payload["observed_at"] is None
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_code"] == "MARKET_CALENDAR_UNAVAILABLE"
    assert context["market_temperature_score"] is None
    assert context["market_temperature_observed_at"] is None
    assert context["market_temperature_band"] == "unavailable"
    assert context["market_temperature_degraded"] is True
    assert context["market_temperature_blocked_reason"] == payload["blocked_reason"]
    assert "5日 不可用" in normalized
    assert "· 20日 不可用" in normalized
    assert "5日 → 0.0" not in normalized
    assert "· 20日 → 0.0" not in normalized
    assert "pulse-card__date" not in rendered
    assert payload["blocked_reason"] in normalized


@pytest.mark.parametrize(
    ("change_5d", "change_20d", "expected_5d", "expected_20d"),
    [
        (None, 0.0, "5日 不可用", "· 20日 → 0.0"),
        (0.0, None, "5日 → 0.0", "· 20日 不可用"),
        (1.2, -3.4, "5日 ↑ 1.2", "· 20日 ↓ -3.4"),
    ],
)
def test_market_thermometer_change_rendering_preserves_missing_zero_and_direction(
    change_5d: float | None,
    change_20d: float | None,
    expected_5d: str,
    expected_20d: str,
) -> None:
    context = _build_market_thermometer_context(
        {
            "score": 50.0,
            "band": "warm",
            "change_5d": change_5d,
            "change_20d": change_20d,
        }
    )

    rendered = render_to_string("components/market_thermometer_card.html", context)
    normalized = " ".join(rendered.split())

    assert expected_5d in normalized
    assert expected_20d in normalized
    if change_5d is None:
        assert "5日 → 0.0" not in normalized
    if change_20d is None:
        assert "· 20日 → 0.0" not in normalized


@pytest.mark.parametrize(
    "error",
    [
        DataFetchError("Unexpected data source failure", code="MARKET_DATA_SOURCE_FAILED"),
        RuntimeError("Unexpected market thermometer failure"),
    ],
)
def test_load_market_thermometer_payload_propagates_unrecognized_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def raise_error(
        *,
        user_id: int | None,
        use_personal_thresholds: bool,
    ) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(
        dashboard_regime_context.data_center_interface_services,
        "load_market_thermometer_payload",
        raise_error,
    )

    with pytest.raises(type(error)) as caught:
        _load_market_thermometer_payload(user_id=17)

    assert caught.value is error
