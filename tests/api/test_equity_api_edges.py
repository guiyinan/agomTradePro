from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    PriceBarModel,
)
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
            timestamp=datetime(2026, 4, 3, 9, 30, 0, tzinfo=UTC),
            price=10.98,
            avg_price=10.98,
            volume=4482,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 31, 0, tzinfo=UTC),
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


@pytest.mark.django_db
def test_equity_valuation_returns_basic_info_when_valuation_missing(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    PriceBarModel.objects.create(
        asset_code="300308.SZ",
        bar_date=today,
        freq="1d",
        adjustment="none",
        open="600.00",
        high="610.00",
        low="598.00",
        close="606.52",
        volume="100000.00",
        amount="60652000.00",
        source="test",
    )

    response = authenticated_client.get("/api/equity/valuation/300308.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert payload["market"] == "SZ"
    assert payload["latest_valuation"]["price"] == 606.52
    assert payload["latest_valuation"]["pe"] is None
    assert "估值数据" in payload["error"]


@pytest.mark.django_db
def test_equity_intraday_chart_uses_data_center_stock_info(authenticated_client):
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    intraday_points = [
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 30, 0, tzinfo=UTC),
            price=606.00,
            avg_price=606.00,
            volume=1234,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 31, 0, tzinfo=UTC),
            price=606.52,
            avg_price=606.26,
            volume=5678,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_intraday_points",
        return_value=intraday_points,
    ):
        response = authenticated_client.get("/api/equity/intraday/300308.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["points"]) == 2
    assert payload["latest_point"]["price"] == 606.52


@pytest.mark.django_db
def test_equity_technical_chart_uses_tushare_gateway_bar_fallback(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    remote_bars = [
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=2),
            open=600.0,
            high=612.0,
            low=598.0,
            close=606.0,
            volume=100000,
            amount=60000000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=1),
            open=606.0,
            high=625.0,
            low=594.35,
            close=606.52,
            volume=290271,
            amount=17694513.705,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository._get_tushare_gateway_historical_bars",
        return_value=remote_bars,
    ):
        response = authenticated_client.get("/api/equity/technical/300308.SZ/?timeframe=day&lookback_days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["candles"]) == 2
    assert payload["candles"][-1]["close"] == 606.52
    cached_rows = StockDailyModel.objects.filter(stock_code="300308.SZ").order_by("trade_date")
    assert cached_rows.count() == 2
    assert cached_rows.last().close == Decimal("606.52")


@pytest.mark.django_db
def test_equity_regime_correlation_uses_tushare_gateway_daily_price_fallback(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    remote_bars = [
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=2),
            open=598.0,
            high=602.0,
            low=596.0,
            close=600.0,
            volume=100000,
            amount=59800000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=1),
            open=600.0,
            high=608.0,
            low=599.0,
            close=606.0,
            volume=120000,
            amount=72600000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today,
            open=606.0,
            high=607.0,
            low=603.0,
            close=606.52,
            volume=90000,
            amount=54586800.0,
        ),
    ]
    remote_prices = [
        (today - timedelta(days=2), Decimal("600.00")),
        (today - timedelta(days=1), Decimal("606.00")),
        (today, Decimal("606.52")),
    ]
    regime_history = {
        today - timedelta(days=1): "Recovery",
        today: "Overheat",
    }
    market_returns = {
        today - timedelta(days=1): 0.005,
        today: 0.001,
    }

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository._get_tushare_gateway_historical_bars",
        return_value=remote_bars,
    ), patch(
        "apps.equity.application.use_cases.AnalyzeRegimeCorrelationUseCase._get_regime_history",
        return_value=regime_history,
    ), patch(
        "apps.equity.application.use_cases.AnalyzeRegimeCorrelationUseCase._get_market_returns",
        return_value=market_returns,
    ):
        response = authenticated_client.get("/api/equity/regime-correlation/300308.SZ/?lookback_days=252")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["regime_performance"]) == 4
    cached_rows = StockDailyModel.objects.filter(stock_code="300308.SZ").order_by("trade_date")
    assert cached_rows.count() == len(remote_prices)
    assert cached_rows.last().close == Decimal("606.52")
