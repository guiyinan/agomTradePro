"""Contracts for the owner-scoped aggregate curve replacing the sidecar."""

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.dashboard.application.performance_curve import build_performance_curve_payload
from apps.simulated_trading.application import query_services
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_dashboard_overview import (
    RUNTIME_DASHBOARD_OVERVIEW_ACTIONS,
)


@pytest.mark.parametrize(
    ("range_code", "days"),
    [("1M", 30), ("3M", 90), ("6M", 180), ("1Y", 365), ("ALL", None)],
)
def test_curve_passes_real_range_to_owner_query(range_code, days):
    query = Mock(return_value=[{"date": "2026-10-01", "portfolio_value": 123.0}])
    result = build_performance_curve_payload(user_id=7, range_code=range_code, query=query)
    query.assert_called_once_with(user_id=7, account_id=None, days=days)
    assert result["series"] == query.return_value
    assert result["range"] == range_code
    assert result["has_history"] is True


def test_curve_no_history_stays_empty_and_invalid_range_never_queries():
    query = Mock(return_value=[])
    assert build_performance_curve_payload(user_id=7, range_code="all", query=query)["series"] == []
    assert build_performance_curve_payload(user_id=7, query=query)["has_history"] is False
    query.reset_mock()
    with pytest.raises(ValueError, match="range"):
        build_performance_curve_payload(user_id=7, range_code="2Y", query=query)
    query.assert_not_called()


@pytest.mark.parametrize("days", [30, 90, 180, 365, None])
def test_aggregate_query_bounds_and_owner_scope(monkeypatch, days):
    today = date.today()
    account_repo = Mock()
    account_repo.get_by_user.return_value = [
        SimpleNamespace(account_id=3, initial_capital=100),
        SimpleNamespace(account_id=4, initial_capital=200),
    ]
    daily_repo = Mock()
    daily_repo.list_daily_records.side_effect = lambda account_id, **kwargs: [
        {
            "record_date": today,
            "net_value": account_id * 100,
            "cash": 1,
            "market_value": 2,
            "positions_count": 1,
        }
    ]
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(
        query_services, "get_simulated_daily_net_value_repository", lambda: daily_repo
    )
    rows = query_services.get_user_performance_payload(user_id=17, account_id=None, days=days)
    account_repo.get_by_user.assert_called_once_with(17)
    assert [call.args[0] for call in daily_repo.list_daily_records.call_args_list] == [3, 4]
    for call in daily_repo.list_daily_records.call_args_list:
        assert call.kwargs == {
            "start_date": today - timedelta(days=days - 1) if days else None,
            "end_date": today,
        }
    assert rows[0]["portfolio_value"] == 700.0


def test_tui_curve_exposes_range_and_plots_value_separately_from_percentage():
    action = next(
        a
        for a in RUNTIME_DASHBOARD_OVERVIEW_ACTIONS
        if a["key"] == "dashboard.portfolio-performance"
    )
    assert action["endpoint"] == "/api/dashboard/v1/equity-curve/"
    assert (action["method"], action["risk"], action["effect"]) == ("GET", "read", "read")
    range_field = action["fields"][0]
    assert range_field["presentation_semantic"] == "primary_selector"
    assert range_field["options"] == [
        {"value": "1M", "label": "近30天"},
        {"value": "3M", "label": "近90天"},
        {"value": "6M", "label": "近180天"},
        {"value": "1Y", "label": "近365天"},
        {"value": "ALL", "label": "全部历史"},
    ]
    ia_path = (
        Path(__file__).resolve().parents[2] / "config/tui/ia/tui_information_architecture.v1.json"
    )
    ia = json.loads(ia_path.read_text(encoding="utf-8"))
    screen = next(
        item
        for item in [*ia["published_screens"], *ia["runtime_screens"]]
        if item["key"] == "command-center.overview"
    )
    panel = next(
        item for item in screen["dashboard_panels"] if item["key"] == "portfolio-performance"
    )
    assert panel["filter_fields"] == [range_field["key"]]
    service = TuiWorkbenchService(metadata_repository=Mock())
    result = service._to_view_model(
        action=action,
        payload={
            "range": "ALL",
            "has_history": True,
            "series": [{"date": "2026-10-01", "portfolio_value": 123.0, "return_pct": 3.0}],
        },
        status_code=200,
    )
    assert result["series"] == [
        {
            "key": "portfolio_value",
            "label": "账户总资产（元）",
            "points": [{"label": "2026-10-01", "value": 123.0}],
        }
    ]


@pytest.mark.parametrize("late_basis", [200, 0, -1])
def test_historical_return_uses_only_recorded_accounts_and_refuses_unknown_basis(
    monkeypatch, late_basis
):
    today = date.today()
    earlier = today - timedelta(days=400)
    account_repo = Mock()
    account_repo.get_by_user.return_value = [
        SimpleNamespace(account_id=1, initial_capital=100),
        SimpleNamespace(account_id=2, initial_capital=late_basis),
    ]
    daily_repo = Mock()
    daily_repo.list_daily_records.side_effect = lambda account_id, **kwargs: (
        [{"record_date": earlier, "net_value": 110}, {"record_date": today, "net_value": 110}]
        if account_id == 1
        else [{"record_date": today, "net_value": 220}]
    )
    monkeypatch.setattr(query_services, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(
        query_services, "get_simulated_daily_net_value_repository", lambda: daily_repo
    )
    rows = query_services.get_user_performance_payload(user_id=17, account_id=None, days=None)
    assert rows[0]["return_pct"] == 10.0
    assert rows[1]["return_pct"] == (10.0 if late_basis > 0 else None)
