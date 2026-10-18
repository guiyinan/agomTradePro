"""Regression coverage for nullable dashboard valuation summaries."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.dashboard.application.dashboard_data_contracts import DashboardData
from apps.dashboard.application.interface_services import ensure_dashboard_positions


def _dashboard_data(
    *,
    invested_value: float | None,
    invested_ratio: float | None,
    positions: list[dict[str, Any]] | None = None,
) -> DashboardData:
    """Build a complete dashboard DTO while preserving nullable valuation."""

    position_rows = positions or []
    return DashboardData(
        user_id=17,
        username="nullable-dashboard-user",
        display_name="Nullable dashboard user",
        current_regime="Recovery",
        regime_date=None,
        regime_confidence=0.82,
        total_assets=None,
        initial_capital=1000.0,
        total_return=None,
        total_return_pct=None,
        cash_balance=1000.0,
        invested_value=invested_value,
        invested_ratio=invested_ratio,
        positions=position_rows,
        position_count=len(position_rows),
        regime_match_score=0.0,
        regime_recommendations=[],
        active_signals=[],
        signal_stats={},
        asset_allocation=[],
        ai_insights=[],
    )


def test_unknown_invested_value_does_not_hide_fallback_holdings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown value total is not evidence that the account has no positions."""

    data = _dashboard_data(invested_value=None, invested_ratio=None)
    fallback_positions: list[dict[str, Any]] = [
        {
            "asset_code": "510300.SH",
            "quantity": 300,
            "valuation_known": False,
            "market_value": None,
        }
    ]

    def load_fallback(
        user_id: int,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        assert user_id == 17
        assert account_id is None
        return fallback_positions

    monkeypatch.setattr(
        "apps.dashboard.application.interface_services.load_simulated_positions_fallback",
        load_fallback,
    )

    result = ensure_dashboard_positions(data, user_id=17)

    assert result.positions == fallback_positions
    assert result.position_count == 1
    assert result.invested_value is None
    assert result.invested_ratio is None


@pytest.mark.django_db
def test_tui_overview_serializes_unknown_investment_summary_as_null(
    client: Client,
    auth_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown totals and ratios remain JSON null through the real TUI endpoint."""

    client.force_login(auth_user)
    monkeypatch.setattr(
        "apps.dashboard.interface.tui_views.build_dashboard_data",
        lambda user_id: _dashboard_data(invested_value=None, invested_ratio=None),
    )

    response = client.get("/api/dashboard/tui/overview/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    summary = response.json()["summary"]
    assert summary["invested_value"] is None
    assert summary["invested_ratio_percent"] is None
    assert summary["total_assets"] is None
