from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, date, datetime
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
    observed_at = datetime.now(UTC).isoformat()
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = [
        {
            "asset_code": "000001.SH",
            "price": 3200.5,
            "change": 12.3,
            "change_pct": 0.39,
            "volume": 1000,
            "timestamp": observed_at,
        },
        {
            "asset_code": "399006.SZ",
            "price": 2100.1,
            "change": -5.1,
            "change_pct": -0.24,
            "volume": 500,
            "timestamp": observed_at,
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
    assert payload["timestamp"] == observed_at
    assert payload["available_index_count"] == 2
    assert payload["is_partial"] is True
    assert payload["must_not_use_for_decision"] is True
    assert payload["contract"]["missing_index_codes"] == ["399001.SZ"]


@pytest.mark.django_db
def test_market_summary_reads_governed_market_breadth(client):
    observed_at = datetime.now(UTC).isoformat()
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = [
        {
            "asset_code": code,
            "price": price,
            "change": None,
            "change_pct": None,
            "volume": 100,
            "timestamp": observed_at,
        }
        for code, price in (
            ("000001.SH", 3800.0),
            ("399001.SZ", 13200.0),
            ("399006.SZ", 3200.0),
        )
    ]
    breadth = {
        "up_count": 3120,
        "down_count": 1780,
        "limit_up_count": 88,
        "limit_down_count": 7,
        "stats_available": True,
        "contract": {
            "observed_at": "2026-07-30",
            "market_data_as_of": "2026-07-30",
            "is_reliable": True,
            "is_stale": False,
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        },
    }

    with (
        patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case),
        patch(
            "apps.realtime.interface.views.get_market_breadth_payload",
            return_value=breadth,
        ),
    ):
        response = client.get("/api/realtime/market-summary/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats_available"] is True
    assert payload["up_count"] == 3120
    assert payload["down_count"] == 1780
    assert payload["limit_up_count"] == 88
    assert payload["limit_down_count"] == 7
    assert payload["breadth_contract"] == breadth["contract"]


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
    assert payload["must_not_use_for_decision"] is True
    assert payload["contract"]["is_reliable"] is False
    assert "cache or configured providers" in payload["message"]


@pytest.mark.django_db
def test_market_summary_marks_complete_fresh_index_set_reliable(client):
    observed_at = datetime.now(UTC).isoformat()
    mock_use_case = Mock()
    mock_use_case.get_latest_prices.return_value = [
        {
            "asset_code": code,
            "price": price,
            "change": None,
            "change_pct": None,
            "volume": 100,
            "timestamp": observed_at,
        }
        for code, price in (
            ("000001.SH", 3804.69),
            ("399001.SZ", 13285.80),
            ("399006.SZ", 3244.62),
        )
    ]

    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        response = client.get("/api/realtime/market-summary/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available_index_count"] == 3
    assert payload["is_partial"] is False
    assert payload["must_not_use_for_decision"] is False
    assert payload["contract"] == {
        "observed_at": observed_at,
        "market_data_as_of": observed_at,
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "missing_index_codes": [],
    }


@pytest.mark.django_db
def test_realtime_health_timeout_returns_unhealthy_payload(client):
    mock_use_case = Mock()
    mock_use_case.service = Mock()
    mock_use_case.service.config.to_dict.return_value = {"provider": "mock"}

    mock_future = Mock()
    mock_future.result.side_effect = FutureTimeoutError()
    mock_executor = Mock()
    mock_executor.submit.return_value = mock_future

    with (
        patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case),
        patch(
            "apps.realtime.interface.views.ThreadPoolExecutor",
            return_value=mock_executor,
        ),
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
    assert response.json()["results"][0]["is_stale"] is True
    assert response.json()["results"][0]["must_not_use_for_decision"] is True
    assert response.json()["results"][0]["blocked_reason"] == "sector_price_stale"
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
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
    query.assert_called_once_with(direction="up", limit=2)

    unknown_response = client.get("/api/realtime/top-movers/", {"refresh": True})
    assert unknown_response.status_code == 400
    assert "Unknown query parameters: refresh" in str(unknown_response.json())

    client.logout()
    anonymous_response = client.get("/api/realtime/top-movers/")
    assert anonymous_response.status_code in {401, 403}
