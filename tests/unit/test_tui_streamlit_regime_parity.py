"""Focused current-Regime and quadrant-projection parity contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.regime.application import interface_services
from apps.regime.interface import tui_views
from apps.regime.interface.tui_views import RegimeTuiOverviewView
from apps.terminal.application.tui_workbench import TuiWorkbenchService


class _HistoryUseCase:
    def execute(self, start_date: date, end_date: date) -> dict[str, Any]:
        return {
            "pulse_history": [],
            "action_history": [],
            "regime_transitions": [],
        }


def _current_payload(
    *,
    observed_at: date | None,
    blocked: bool = False,
) -> dict[str, Any]:
    blocked_reason = "regime_macro_observation_stale" if blocked else ""
    freshness_status = "stale" if blocked else "fresh"
    regime = "Unknown" if blocked else "Recovery"
    return {
        "success": True,
        "data": {
            "observed_at": observed_at,
            "dominant_regime": regime,
            "confidence": 0.75,
            "growth_momentum_z": 0.2,
            "inflation_momentum_z": -0.1,
            "distribution": {
                "Recovery": 0.75,
                "Overheat": 0.005,
                "Stagflation": 0.095,
                "Deflation": 0.15,
            },
            "source": "tushare",
            "growth_level": "up",
            "inflation_level": "down",
            "growth_value": 51.2,
            "inflation_value": 1.4,
            "is_fallback": False,
            "warnings": ["源观察窗口已校验"],
            "diagnostic_regime": "Recovery",
            "is_stale": blocked,
            "must_not_use_for_decision": blocked,
            "blocked_reason": blocked_reason,
            "contract": {
                "observed_at": observed_at,
                "market_data_as_of": observed_at,
                "freshness_status": freshness_status,
                "is_stale": blocked,
                "must_not_use_for_decision": blocked,
                "blocked_reason": blocked_reason,
            },
        },
    }


def _call_tui_overview(
    monkeypatch: pytest.MonkeyPatch,
    query: str = "",
) -> Any:
    monkeypatch.setattr(RegimeTuiOverviewView, "throttle_classes", ())
    request = APIRequestFactory().get(f"/api/regime/tui/overview/{query}")
    force_authenticate(request, user=SimpleNamespace(pk=1, is_authenticated=True))
    return RegimeTuiOverviewView.as_view()(request)


def _project_quadrant(payload: dict[str, Any]) -> dict[str, Any]:
    service = TuiWorkbenchService(metadata_repository=object())
    return service._regime_current_result_model(
        {"key": "regime.current", "label": "当前宏观象限"},
        payload,
        200,
    )


def test_current_regime_payload_forwards_explicit_source_and_preserves_source_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current owner must keep its source observation distinct from the query cutoff."""

    observed_at = date(2026, 7, 30)
    as_of_date = date(2026, 7, 31)
    current = SimpleNamespace(
        observed_at=observed_at,
        dominant_regime="Recovery",
        confidence=0.75,
        growth_momentum_z=0.2,
        inflation_momentum_z=-0.1,
        distribution={"Recovery": 0.75},
        data_source="tushare",
        growth_indicator="PMI",
        inflation_indicator="CPI",
        growth_level="up",
        inflation_level="down",
        growth_value=51.2,
        inflation_value=1.4,
        is_fallback=False,
        warnings=[],
        diagnostic_regime="Recovery",
        is_stale=False,
        must_not_use_for_decision=False,
        blocked_reason="",
    )
    calls: dict[str, Any] = {}

    def _resolve(**kwargs: Any) -> SimpleNamespace:
        calls.update(kwargs)
        return current

    monkeypatch.setattr(interface_services.current_regime, "resolve_current_regime", _resolve)

    payload = interface_services.get_regime_current_payload(
        as_of_date=as_of_date,
        data_source="tushare",
    )

    assert calls == {"as_of_date": as_of_date, "data_source": "tushare"}
    assert payload["data"]["observed_at"] == observed_at
    assert payload["data"]["contract"]["market_data_as_of"] == observed_at
    assert payload["data"]["contract"]["freshness_status"] == "fresh"


def test_regime_tui_overview_uses_fresh_owner_quadrant_and_percent_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current quadrant and probabilities come from the freshness-gated owner read."""

    as_of_date = date(2026, 7, 31)
    observed_at = date(2026, 7, 30)
    owner_payload = _current_payload(observed_at=observed_at)
    dashboard_calls: list[dict[str, Any]] = []

    def _dashboard(**kwargs: Any) -> dict[str, Any]:
        dashboard_calls.append(kwargs)
        return {
            "regime_result": {
                "quadrant": "Overheat",
                "confidence": 0.99,
                "pmi_trend": "up",
                "cpi_trend": "down",
                "growth_dates": '["2026-06", "2026-07"]',
                "growth_values": "[50.8, 51.2]",
                "inflation_dates": '["2026-06", "2026-07"]',
                "inflation_values": "[1.3, 1.4]",
            },
            "warnings": [],
            "error": None,
            "current_source": "tushare",
        }

    monkeypatch.setattr(tui_views, "get_regime_current_payload", lambda **_: owner_payload)
    monkeypatch.setattr(tui_views, "get_regime_dashboard_payload", _dashboard)
    monkeypatch.setattr(tui_views, "GetRegimeNavigatorHistoryUseCase", _HistoryUseCase)

    response = _call_tui_overview(
        monkeypatch,
        "?as_of_date=2026-07-31&source=tushare",
    )

    assert response.status_code == 200
    payload = response.data
    summary = payload["summary"]
    assert payload["available"] is True
    assert summary["quadrant"] == "Recovery"
    assert summary["confidence_percent"] == 75.0
    assert summary["as_of_date"] == as_of_date.isoformat()
    assert summary["observed_at"] == observed_at.isoformat()
    assert summary["freshness_status"] == "fresh"
    assert summary["must_not_use_for_decision"] is False
    assert summary["growth_level"] == 51.2
    assert summary["inflation_level"] == 1.4
    assert payload["distribution"] == [
        {"regime": "Recovery", "probability_percent": 75.0},
        {"regime": "Overheat", "probability_percent": 0.5},
        {"regime": "Stagflation", "probability_percent": 9.5},
        {"regime": "Deflation", "probability_percent": 15.0},
    ]
    assert payload["contract"]["observed_at"] == observed_at.isoformat()
    assert payload["contract"]["as_of_date"] == as_of_date.isoformat()
    assert dashboard_calls[0]["requested_source"] == "tushare"
    assert dashboard_calls[0]["as_of_date"] == as_of_date

    view_model = _project_quadrant(payload)
    fields = {field["key"]: field["value"] for field in view_model["fields"]}
    assert fields["observed_at"] == observed_at.isoformat()
    assert fields["as_of_date"] == as_of_date.isoformat()
    assert "源观测" in fields["trend"]
    assert "分析截至" in fields["trend"]
    assert "2026-07-30" in fields["trend"]
    assert "2026-07-31" in fields["trend"]
    assert view_model["freshness_status"] == "fresh"
    assert view_model["freshness_status_label"] == "数据新鲜"
    assert view_model["confidence_unit"] == "percent"
    assert view_model["quadrant_distribution"] == payload["distribution"]
    assert view_model["quadrant_distribution"][1]["probability_percent"] == 0.5
    assert view_model["must_not_use_for_decision"] is False
    incomplete_distribution_model = _project_quadrant(
        {**payload, "distribution": payload["distribution"][:-1]}
    )
    assert incomplete_distribution_model["quadrant_distribution"] == []


def test_regime_tui_overview_hides_blocked_current_probabilities_and_projects_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale source data must remain visible as blocked evidence, not as a current quadrant."""

    observed_at = date(2026, 5, 31)
    owner_payload = _current_payload(observed_at=observed_at, blocked=True)

    def _unexpected_dashboard(**_: Any) -> dict[str, Any]:
        pytest.fail("Blocked current Regime data must not trigger a second display calculation")

    monkeypatch.setattr(tui_views, "get_regime_current_payload", lambda **_: owner_payload)
    monkeypatch.setattr(tui_views, "get_regime_dashboard_payload", _unexpected_dashboard)
    monkeypatch.setattr(tui_views, "GetRegimeNavigatorHistoryUseCase", _HistoryUseCase)

    response = _call_tui_overview(monkeypatch, "?as_of_date=2026-07-31")

    assert response.status_code == 200
    payload = response.data
    assert payload["available"] is False
    assert payload["distribution"] == []
    assert payload["momentum"] == []
    assert payload["summary"]["quadrant"] == "Unknown"
    assert payload["summary"]["confidence_percent"] is None
    assert payload["summary"]["as_of_date"] == "2026-07-31"
    assert payload["summary"]["observed_at"] == observed_at.isoformat()
    assert payload["summary"]["freshness_status"] == "stale"
    assert payload["summary"]["must_not_use_for_decision"] is True
    assert payload["summary"]["error"] == "regime_macro_observation_stale"
    assert payload["contract"]["blocked_reason"] == "regime_macro_observation_stale"

    view_model = _project_quadrant(payload)
    fields = {field["key"]: field["value"] for field in view_model["fields"]}
    assert view_model["status"] == "不可用于决策"
    assert view_model["blocked_reason_code"] == "regime_macro_observation_stale"
    assert view_model["must_not_use_for_decision"] is True
    assert view_model["quadrant_distribution"] == []
    assert view_model["confidence_unit"] == "percent"
    assert fields["confidence"] == "-"
    assert fields["observed_at"] == observed_at.isoformat()
    assert fields["as_of_date"] == "2026-07-31"
    assert "stale" in fields["warning"]
    assert "源观测" in fields["trend"]
