from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.sector.infrastructure.models import SectorIndexModel, SectorInfoModel


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


@pytest.mark.django_db
def test_sector_performance_is_strict_authenticated_persisted_read(client):
    user = get_user_model().objects.create_user(
        username="realtime_sector_user",
        password="testpass123",
    )
    client.force_login(user)
    sector = SectorInfoModel._default_manager.create(
        sector_code="801780",
        sector_name="银行",
        level="SW1",
    )
    SectorIndexModel._default_manager.create(
        sector_code=sector.sector_code,
        trade_date=date(2026, 7, 11),
        open_price=Decimal("1000.00"),
        high=Decimal("1020.00"),
        low=Decimal("990.00"),
        close=Decimal("1010.00"),
        volume=1000,
        amount=Decimal("1000000.00"),
        change_pct=1.2,
    )
    before = {
        "sectors": list(SectorInfoModel._default_manager.order_by("pk").values()),
        "indices": list(SectorIndexModel._default_manager.order_by("pk").values()),
    }

    response = client.get("/api/realtime/sector-performance/")
    unknown_response = client.get(
        "/api/realtime/sector-performance/",
        {"refresh": True},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["sector_code"] == sector.sector_code
    assert response.json()["results"][0]["change_percent"] == 1.2
    assert unknown_response.status_code == 400
    assert "Unknown query parameters: refresh" in str(unknown_response.json())
    after = {
        "sectors": list(SectorInfoModel._default_manager.order_by("pk").values()),
        "indices": list(SectorIndexModel._default_manager.order_by("pk").values()),
    }
    assert after == before

    client.logout()
    anonymous_response = client.get("/api/realtime/sector-performance/")
    assert anonymous_response.status_code in {401, 403}


@pytest.mark.django_db
def test_top_movers_is_authenticated_cached_read(client):
    user = get_user_model().objects.create_user(
        username="realtime_movers_user",
        password="testpass123",
    )
    client.force_login(user)
    cached = [
        {"asset_code": "000001.SZ", "change_pct": "2.5"},
        {"asset_code": "600000.SH", "change_pct": "1.2"},
    ]

    with patch(
        "apps.realtime.interface.views.list_cached_top_movers_payloads",
        return_value=cached,
    ) as query:
        response = client.get(
            "/api/realtime/top-movers/",
            {"direction": "up", "limit": 2},
        )

    assert response.status_code == 200
    assert response.json() == {
        "results": cached,
        "count": 2,
        "source": "cached_monitored_prices",
    }
    query.assert_called_once_with(direction="up", limit=2)

    unknown_response = client.get("/api/realtime/top-movers/", {"refresh": True})
    assert unknown_response.status_code == 400
    assert "Unknown query parameters: refresh" in str(unknown_response.json())

    client.logout()
    anonymous_response = client.get("/api/realtime/top-movers/")
    assert anonymous_response.status_code in {401, 403}
