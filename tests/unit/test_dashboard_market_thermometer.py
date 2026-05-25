"""Tests for dashboard market thermometer context wiring."""

from __future__ import annotations

from types import SimpleNamespace

from apps.dashboard.interface.views import (
    _build_attention_items_context,
    _build_market_thermometer_context,
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
