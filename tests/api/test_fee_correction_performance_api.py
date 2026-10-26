"""Full-app API contract for the correction-aware performance payload."""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.application.use_cases import AccountPerformanceResult
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from apps.simulated_trading.interface import _portfolio_views


def test_performance_api_nested_metrics_match_single_use_case_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimulatedAccount(
        account_id=41,
        account_name="api performance correction",
        account_type=AccountType.SIMULATED,
        initial_capital=100.0,
        current_cash=60.0,
        current_market_value=50.0,
        total_value=110.0,
        total_return=35.0,
        annual_return=12.0,
        max_drawdown=8.0,
        sharpe_ratio=1.4,
        win_rate=80.0,
        total_trades=10,
        winning_trades=8,
        start_date=date(2025, 1, 1),
    )
    performance = {
        "total_return": None,
        "annual_return": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "win_rate": None,
    }
    original_performance = {
        "total_return": 35.0,
        "annual_return": 12.0,
        "max_drawdown": 8.0,
        "sharpe_ratio": 1.4,
        "win_rate": 80.0,
    }
    result: AccountPerformanceResult = {
        "account": account,
        "positions": [],
        "total_positions": 0,
        "total_trades": 3,
        "winning_trades": None,
        "win_rate": None,
        "win_rate_known": False,
        "performance": performance,
        "original_performance": original_performance,
        "performance_metrics_known": False,
        "performance_reason_code": "FEE_CORRECTION_HISTORY_UNKNOWN",
        "performance_source": "unknown",
    }
    executions: list[int] = []

    class _UseCase:
        def __init__(self, *_args: object) -> None:
            pass

        def execute(self, account_id: int) -> AccountPerformanceResult:
            executions.append(account_id)
            return result

    monkeypatch.setattr(interface_services, "get_account_repository", lambda: object())
    monkeypatch.setattr(interface_services, "get_position_repository", lambda: object())
    monkeypatch.setattr(interface_services, "get_trade_repository", lambda: object())
    monkeypatch.setattr(interface_services, "get_daily_net_value_repository", lambda: object())
    monkeypatch.setattr(
        interface_services,
        "has_current_position_valuation",
        lambda _account_id: True,
    )
    monkeypatch.setattr(
        interface_services,
        "has_complete_closed_trade_costs",
        lambda _account_id: True,
    )
    monkeypatch.setattr(
        _portfolio_views,
        "_get_owned_account_or_response",
        lambda *_args, **_kwargs: account,
    )
    monkeypatch.setattr(_portfolio_views, "GetAccountPerformanceUseCase", _UseCase)

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/41/performance/", HTTP_ACCEPT="application/json"
    )
    force_authenticate(request, user=get_user_model()(pk=17, username="performance-contract"))
    response = _portfolio_views.PerformanceAPIView.as_view()(request, account_id=41)
    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"

    assert response.data["account"]["total_return"] is None
    assert response.data["account"]["annual_return"] is None
    assert response.data["account"]["max_drawdown"] is None
    assert response.data["account"]["sharpe_ratio"] is None
    assert response.data["account"]["win_rate"] is None
    assert response.data["account"]["total_trades"] == 3
    assert response.data["account"]["winning_trades"] is None
    assert response.data["original_performance"] == original_performance
    assert response.data["performance_reason_code"] == "FEE_CORRECTION_HISTORY_UNKNOWN"
    assert executions == [41]
