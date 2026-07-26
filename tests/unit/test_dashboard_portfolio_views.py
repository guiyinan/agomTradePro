"""Dashboard portfolio view boundary tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.dashboard.interface import portfolio_views, views
from apps.dashboard.interface.portfolio_views import _generate_allocation_from_positions


def test_generate_allocation_groups_valid_finite_market_values():
    allocation = _generate_allocation_from_positions(
        [
            {"asset_class_display": "股票", "market_value": 100.5},
            {"asset_class": "股票", "market_value": "20"},
            {"asset_class": "", "market_value": 10},
        ]
    )

    assert allocation == {"股票": 120.5, "其他": 10.0}


@pytest.mark.parametrize("market_value", [None, "bad", float("nan"), float("inf"), -1])
def test_generate_allocation_rejects_invalid_market_value(market_value):
    with pytest.raises(ValueError, match="position_market_value_invalid"):
        _generate_allocation_from_positions([{"asset_class": "股票", "market_value": market_value}])


def test_allocation_chart_fails_closed_for_invalid_position_value(monkeypatch):
    request = RequestFactory().get("/api/dashboard/allocation/")
    request.user = SimpleNamespace(
        id=7,
        pk=7,
        is_authenticated=True,
        is_active=True,
        username="admin",
    )
    monkeypatch.setattr(
        views,
        "_load_simulated_positions_fallback",
        lambda user_id, account_id=None: [{"asset_class": "股票", "market_value": float("nan")}],
    )

    response = portfolio_views.allocation_chart_htmx(request)
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    payload = json.loads(response.content)

    assert response.status_code == 503
    assert payload == {
        "success": False,
        "error": "资产配置数据暂不可用，请先检查持仓市值。",
        "error_code": "allocation_data_unavailable",
        "must_not_use_for_decision": True,
    }
