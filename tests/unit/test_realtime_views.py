from unittest.mock import Mock, patch

import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


def _build_mock_use_case(prices=None, snapshot=None, is_available=True):
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = prices if prices is not None else []
    mock_use_case.execute_price_polling.return_value = snapshot if snapshot is not None else {}
    mock_use_case.price_provider = Mock()
    mock_use_case.price_provider.is_available.return_value = is_available
    mock_use_case.service = Mock()
    mock_use_case.service.config.to_dict.return_value = {"provider": "mock"}
    mock_use_case.service.price_repository = Mock()
    latest = Mock()
    latest.timestamp.isoformat.return_value = "2026-02-26T10:00:00+08:00"
    mock_use_case.service.price_repository.get_latest_price.return_value = latest
    return mock_use_case


@pytest.mark.django_db
def test_realtime_prices_with_assets_query(client):
    prices = [{"asset_code": "000001.SZ", "price": 10.5}]
    mock_use_case = _build_mock_use_case(prices=prices)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/prices/?assets=000001.SZ")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success_flag"] is True
    assert data["total"] == 1
    assert data["success"] == 1
    assert data["failed"] == 0
    assert data["prices"][0]["asset_code"] == "000001.SZ"


@pytest.mark.django_db
def test_realtime_prices_without_assets_triggers_polling(client):
    snapshot = {"timestamp": "2026-02-26T10:00:00+08:00", "prices": [], "total": 0, "success": 0, "failed": 0}
    mock_use_case = _build_mock_use_case(snapshot=snapshot)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/prices/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success_flag"] is True
    assert data["timestamp"] == "2026-02-26T10:00:00+08:00"


@pytest.mark.django_db
def test_realtime_prices_post_triggers_polling(client):
    snapshot = {"timestamp": "2026-02-26T10:00:00+08:00", "prices": [], "total": 0, "success": 0, "failed": 0}
    mock_use_case = _build_mock_use_case(snapshot=snapshot)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.post("/api/realtime/prices/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success_flag"] is True
    assert data["timestamp"] == "2026-02-26T10:00:00+08:00"


@pytest.mark.django_db
def test_realtime_single_asset_not_found_returns_404(client):
    mock_use_case = _build_mock_use_case(prices=[])
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/prices/000001.SZ/")

    assert resp.status_code == 404
    data = resp.json()
    assert data["success"] is False
    assert "error" in data


@pytest.mark.django_db
def test_realtime_health_view_returns_healthy_status(client):
    mock_use_case = _build_mock_use_case(is_available=True)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/health/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "healthy"
    assert data["data_provider_available"] is True
    assert "timestamp" in data
