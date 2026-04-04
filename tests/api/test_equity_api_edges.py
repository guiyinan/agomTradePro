from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.equity.infrastructure.models import StockDailyModel, StockInfoModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="equity_user",
        password="testpass123",
        email="equity@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_equity_pool_returns_empty_payload_when_no_pool(authenticated_client):
    regime = SimpleNamespace(dominant_regime="Recovery")

    with patch(
        "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
        return_value=[],
    ), patch(
        "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
        return_value=None,
    ), patch(
        "apps.regime.application.current_regime.resolve_current_regime",
        return_value=regime,
    ):
        response = authenticated_client.get("/api/equity/pool/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["regime"] == "Recovery"
    assert payload["count"] == 0
    assert payload["stocks"] == []


@pytest.mark.django_db
def test_equity_refresh_pool_returns_503_when_regime_missing(authenticated_client):
    with patch("apps.regime.application.current_regime.resolve_current_regime", return_value=None):
        response = authenticated_client.post("/api/equity/pool/refresh/", {}, format="json")

    assert response.status_code == 503
    assert response.json()["message"] == "无法获取当前 Regime，请先运行 Regime 判定"


@pytest.mark.django_db
def test_equity_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch(
        "apps.equity.application.services.EquityMultiDimScorer.screen_stocks",
        side_effect=RuntimeError("boom"),
    ):
        response = authenticated_client.post(
            "/api/equity/multidim-screen/",
            {
                "filters": {"sector": "银行"},
                "context": {"regime": "Recovery", "policy_level": "P0", "sentiment_index": 0.1},
                "max_count": 10,
            },
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "筛选失败" in payload["message"]


@pytest.mark.django_db
def test_equity_sync_financial_data_returns_task_payload(authenticated_client):
    task_payload = {"success": True, "queued": True, "task_id": "sync-123"}

    with patch(
        "apps.equity.application.tasks_valuation_sync.sync_financial_data_task",
        return_value=task_payload,
    ) as mock_task:
        response = authenticated_client.post(
            "/api/equity/financial-data/sync/",
            {"stock_codes": ["600519.SH"], "periods": 4, "source": "akshare"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == task_payload
    mock_task.assert_called_once_with(
        source="akshare",
        periods=4,
        stock_codes=["600519.SH"],
    )


@pytest.mark.django_db
def test_equity_technical_chart_rejects_invalid_timeframe(authenticated_client):
    response = authenticated_client.get("/api/equity/technical/000001.SZ/?timeframe=bad")

    assert response.status_code == 400
    assert "timeframe" in response.json()["details"]


@pytest.mark.django_db
def test_equity_technical_chart_returns_candles_and_latest_signal(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    StockDailyModel.objects.bulk_create(
        [
            StockDailyModel(
                stock_code="000001.SZ",
                trade_date=today - timedelta(days=3),
                open="10.00",
                high="10.20",
                low="9.90",
                close="10.00",
                volume=1000,
                amount="1000000.00",
                ma5="9.90",
                ma20="10.00",
                ma60=None,
                macd=-0.10,
                macd_signal=-0.12,
                macd_hist=0.02,
                rsi=48.0,
            ),
            StockDailyModel(
                stock_code="000001.SZ",
                trade_date=today - timedelta(days=2),
                open="10.00",
                high="10.60",
                low="9.95",
                close="10.50",
                volume=1200,
                amount="1200000.00",
                ma5="10.10",
                ma20="10.00",
                ma60=None,
                macd=0.12,
                macd_signal=0.05,
                macd_hist=0.07,
                rsi=55.0,
            ),
        ]
    )

    response = authenticated_client.get("/api/equity/technical/000001.SZ/?timeframe=day&lookback_days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "000001.SZ"
    assert len(payload["candles"]) == 2
    assert payload["latest_signal"]["signal_type"] == "golden_cross"
    assert payload["candles"][-1]["close"] == 10.5


@pytest.mark.django_db
def test_equity_intraday_chart_returns_points(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )

    intraday_points = [
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 30, 0, tzinfo=dt_timezone.utc),
            price=10.98,
            avg_price=10.98,
            volume=4482,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 31, 0, tzinfo=dt_timezone.utc),
            price=11.00,
            avg_price=10.99,
            volume=42820,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_intraday_points",
        return_value=intraday_points,
    ):
        response = authenticated_client.get("/api/equity/intraday/000001.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "000001.SZ"
    assert len(payload["points"]) == 2
    assert payload["latest_point"]["price"] == 11.0
    assert payload["session_date"] == "2026-04-03"
