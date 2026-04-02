from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


def _mock_price(*, price=None, change=None, change_pct=None, volume=0, ts=None):
    return Mock(
        price=price,
        change=change,
        change_pct=change_pct,
        volume=volume,
        timestamp=ts or datetime(2026, 4, 2, 10, 30, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
def test_market_summary_returns_major_index_snapshot(client):
    mock_use_case = Mock()
    mock_provider = Mock()
    mock_provider.get_realtime_price.side_effect = [
        _mock_price(price=3200.5, change=12.3, change_pct=0.39, volume=1000),
        None,
        _mock_price(price=2100.1, change=-5.1, change_pct=-0.24, volume=500),
    ]
    mock_use_case.service = Mock(price_provider=mock_provider)

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


@pytest.mark.django_db
def test_market_summary_returns_503_when_all_indexes_missing(client):
    mock_use_case = Mock()
    mock_provider = Mock()
    mock_provider.get_realtime_price.return_value = None
    mock_use_case.service = Mock(price_provider=mock_provider)

    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        response = client.get("/api/realtime/market-summary/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["timestamp"] is None
    assert payload["sh_index"] is None
    assert payload["sz_index"] is None
    assert payload["cyb_index"] is None


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
