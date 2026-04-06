from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import Mock, patch

import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()

@pytest.mark.django_db
def test_market_summary_returns_major_index_snapshot(client):
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = [
        {
            "asset_code": "000001.SH",
            "price": 3200.5,
            "change": 12.3,
            "change_pct": 0.39,
            "volume": 1000,
            "timestamp": "2026-04-02T10:30:00+00:00",
        },
        {
            "asset_code": "399006.SZ",
            "price": 2100.1,
            "change": -5.1,
            "change_pct": -0.24,
            "volume": 500,
            "timestamp": "2026-04-02T10:31:00+00:00",
        },
    ]

    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        response = client.get("/api/realtime/market-summary/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["sh_index"] == 3200.5
    assert payload["sz_index"] is None
    assert payload["cyb_index"] == 2100.1
    assert payload["total_volume"] == 1500
    assert payload["stats_available"] is False
    assert payload["timestamp"] == "2026-04-02T10:31:00+00:00"


@pytest.mark.django_db
def test_market_summary_returns_503_when_all_indexes_missing(client):
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = []

    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        response = client.get("/api/realtime/market-summary/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["timestamp"] is None
    assert payload["sh_index"] is None
    assert payload["sz_index"] is None
    assert payload["cyb_index"] is None
    assert "cache or configured providers" in payload["message"]


@pytest.mark.django_db
def test_realtime_health_timeout_returns_unhealthy_payload(client):
    mock_use_case = Mock()
    mock_use_case.service = Mock()
    mock_use_case.service.config.to_dict.return_value = {"provider": "mock"}

    mock_future = Mock()
    mock_future.result.side_effect = FutureTimeoutError()
    mock_executor = Mock()
    mock_executor.submit.return_value = mock_future

    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case), patch(
        "apps.realtime.interface.views.ThreadPoolExecutor",
        return_value=mock_executor,
    ):
        response = client.get("/api/realtime/health/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "unhealthy"
    assert payload["data_provider_available"] is False
    assert payload["error"] == "provider_check_timeout"
