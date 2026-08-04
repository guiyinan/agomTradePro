"""API contracts for the Macro and Regime TUI analytical adapters."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.macro.application.trend_filter_service import (
    MacroTrendFilterResult,
    MacroTrendFilterRow,
)


@pytest.mark.django_db
def test_macro_tui_overview_projects_selected_series_and_risk_timeline(
    authenticated_client,
) -> None:
    """The Macro adapter should expose portable rows instead of template JSON."""

    snapshot = {
        "indicator_map": {
            "CN_PMI": {
                "code": "CN_PMI",
                "name": "制造业 PMI",
                "unit": "指数",
                "latest_value": 51.2,
                "latest_period": "2026-06",
                "has_data": True,
                "sync_supported": True,
                "freshness_status": "fresh",
                "decision_grade": "decision_grade",
            }
        },
        "selected_indicator": "CN_PMI",
        "history": [
            {
                "reporting_period_label": "2026-06",
                "value": 51.2,
                "unit": "指数",
                "source": "akshare",
                "freshness_status": "fresh",
                "decision_grade": "decision_grade",
            }
        ],
        "stats": {
            "total_indicators": 1,
            "synced_indicators": 1,
            "total_records": 12,
        },
        "market_thermometer": {
            "market_temperature_score": 62.5,
            "market_temperature_band_label": "偏热",
            "market_temperature_degraded": False,
            "market_temperature_blocked_reason": "",
        },
        "regime_summary": {
            "regime_label": "复苏",
            "confidence": 0.81,
        },
        "pulse_card": {"pulse_composite": 0.25},
        "macro_risk_timeline": {
            "dates": ["2026-06-01"],
            "temperature": [{"date": "2026-06-01", "score": 62.5, "band": "hot"}],
            "pulse": [
                {
                    "date": "2026-06-01",
                    "score": 0.25,
                    "normalized_score": 62,
                }
            ],
            "regime": [
                {
                    "date": "2026-06-01",
                    "regime": "Recovery",
                    "confidence": 0.81,
                }
            ],
        },
    }
    with patch(
        "apps.macro.interface.tui_views.get_macro_data_page_snapshot",
        return_value=snapshot,
    ) as mocked:
        response = authenticated_client.get("/api/macro/tui/overview/?indicator_code=CN_PMI")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"]["selected_indicator_name"] == "制造业 PMI"
    assert payload["summary"]["regime_confidence_percent"] == 81.0
    assert payload["series"] == [
        {
            "period": "2026-06",
            "value": 51.2,
            "unit": "指数",
            "source": "akshare",
            "freshness_status": "fresh",
            "decision_grade": "decision_grade",
        }
    ]
    assert payload["risk_timeline"][0] == {
        "date": "2026-06-01",
        "market_temperature": 62.5,
        "pulse_normalized": 62,
        "regime": "Recovery",
        "regime_confidence_percent": 81.0,
    }
    assert mocked.call_args.kwargs["selected_indicator"] == "CN_PMI"
    assert mocked.call_args.kwargs["can_sync_macro_data"] is False
    assert mocked.call_args.kwargs["published_only"] is True


@pytest.mark.django_db
def test_macro_tui_overview_rejects_unbounded_indicator_code(
    authenticated_client,
) -> None:
    """The query projection must reject unexpectedly large indicator IDs."""

    response = authenticated_client.get(f"/api/macro/tui/overview/?indicator_code={'X' * 81}")

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_macro_tui_trend_filter_projects_portable_chart_rows(
    authenticated_client,
) -> None:
    """The replacement adapter should expose one owner-scoped read model."""

    service_result = MacroTrendFilterResult(
        indicator_code="CN_PMI",
        indicator_name="制造业 PMI",
        filter_type="KALMAN",
        unit="指数",
        data_source="data_center_fact",
        freshness_status="fresh",
        decision_grade="decision_safe",
        must_not_use_for_decision=False,
        blocked_reason="",
        latest_quality="verified",
        start_period="2026-01-01",
        end_period="2026-02-01",
        rows=(
            MacroTrendFilterRow(
                period="2026-01-01",
                original=50.0,
                trend=49.5,
                cycle=0.5,
                slope=0.0,
            ),
            MacroTrendFilterRow(
                period="2026-02-01",
                original=51.0,
                trend=50.5,
                cycle=0.5,
                slope=1.0,
            ),
        ),
    )
    with patch("apps.macro.interface.tui_views.build_macro_trend_filter_service") as builder:
        builder.return_value.execute.return_value = service_result
        response = authenticated_client.get(
            "/api/macro/tui/trend-filter/" "?indicator_code=CN_PMI&filter_type=kalman&limit=120"
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"]["indicator_name"] == "制造业 PMI"
    assert payload["summary"]["filter_type"] == "KALMAN"
    assert payload["summary"]["point_count"] == 2
    assert payload["rows"][1] == {
        "period": "2026-02-01",
        "original": 51.0,
        "trend": 50.5,
        "cycle": 0.5,
        "slope": 1.0,
    }
    builder.return_value.execute.assert_called_once_with(
        indicator_code="CN_PMI",
        filter_type="KALMAN",
        limit=120,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "",
        "indicator_code=bad/value",
        "indicator_code=CN_PMI&filter_type=unknown",
        "indicator_code=CN_PMI&limit=11",
        "indicator_code=CN_PMI&limit=501",
        "indicator_code=CN_PMI&limit=bad",
    ],
)
def test_macro_tui_trend_filter_rejects_invalid_query(
    authenticated_client,
    query: str,
) -> None:
    """Invalid identifiers and windows must fail before composition."""

    response = authenticated_client.get(f"/api/macro/tui/trend-filter/?{query}")

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_regime_tui_overview_projects_distribution_momentum_and_history(
    authenticated_client,
) -> None:
    """The Regime adapter should flatten all chart families into row arrays."""

    dashboard_payload = {
        "regime_result": {
            "quadrant": "Recovery",
            "confidence": 0.75,
            "distribution": {
                "Recovery": 0.75,
                "Overheat": 0.10,
                "Stagflation": 0.05,
                "Deflation": 0.10,
            },
            "pmi_value": 51.2,
            "cpi_value": 1.4,
            "pmi_trend": "up",
            "cpi_trend": "flat",
            "growth_dates": '["2026-05", "2026-06"]',
            "growth_values": "[50.8, 51.2]",
            "inflation_dates": '["2026-05", "2026-06"]',
            "inflation_values": "[1.3, 1.4]",
        },
        "warnings": ["样本窗口较短"],
        "error": None,
        "current_source": "akshare",
    }
    history_payload = {
        "pulse_history": [
            {
                "date": "2026-06-01",
                "composite_score": 0.2,
                "growth_score": 0.3,
                "inflation_score": 0.1,
                "liquidity_score": 0.0,
                "sentiment_score": -0.1,
            }
        ],
        "action_history": [
            {
                "date": "2026-06-01",
                "risk_budget_pct": 55.0,
                "equity_weight": 45.0,
                "bond_weight": 30.0,
                "commodity_weight": 10.0,
                "cash_weight": 15.0,
            }
        ],
        "regime_transitions": [
            {
                "date": "2026-06-01",
                "to_regime": "Recovery",
                "confidence": 0.75,
            }
        ],
    }
    with (
        patch(
            "apps.regime.interface.tui_views.get_regime_dashboard_payload",
            return_value=dashboard_payload,
        ) as dashboard_mock,
        patch(
            "apps.regime.interface.tui_views.GetRegimeNavigatorHistoryUseCase"
        ) as history_use_case,
    ):
        history_use_case.return_value.execute.return_value = history_payload
        response = authenticated_client.get(
            "/api/regime/tui/overview/" "?as_of_date=2026-07-01&source=akshare&months=6"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["summary"]["quadrant"] == "Recovery"
    assert payload["summary"]["confidence_percent"] == 75.0
    assert payload["distribution"][0] == {
        "regime": "Recovery",
        "probability_percent": 75.0,
    }
    assert payload["momentum"] == [
        {"date": "2026-05", "growth": 50.8, "inflation": 1.3},
        {"date": "2026-06", "growth": 51.2, "inflation": 1.4},
    ]
    assert payload["history"][0]["regime"] == "Recovery"
    assert payload["history"][0]["risk_budget_percent"] == 55.0
    assert dashboard_mock.call_args.kwargs["requested_source"] == "akshare"
    assert dashboard_mock.call_args.kwargs["skip_cache"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "as_of_date=2026/07/01",
        "months=0",
        "months=61",
        "months=bad",
    ],
)
def test_regime_tui_overview_rejects_invalid_query(
    authenticated_client,
    query: str,
) -> None:
    """Invalid analytical windows should fail before owner services run."""

    response = authenticated_client.get(f"/api/regime/tui/overview/?{query}")

    assert response.status_code == 400
    assert response.json()["success"] is False
