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
