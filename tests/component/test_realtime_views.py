from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.test import Client

from apps.realtime.application.price_polling_service import (
    PricePollingService,
    PricePollingUseCase,
)
from apps.realtime.domain.entities import AssetType, PricePollingConfig, RealtimePrice


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
    snapshot = {
        "timestamp": "2026-02-26T10:00:00+08:00",
        "prices": [],
        "total": 0,
        "success": 0,
        "failed": 0,
    }
    mock_use_case = _build_mock_use_case(snapshot=snapshot)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/prices/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success_flag"] is True
    assert data["timestamp"] == "2026-02-26T10:00:00+08:00"


@pytest.mark.django_db
def test_realtime_prices_post_triggers_polling(client):
    snapshot = {
        "timestamp": "2026-02-26T10:00:00+08:00",
        "prices": [],
        "total": 0,
        "success": 0,
        "failed": 0,
    }
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
def test_realtime_single_asset_returns_success_contract(client):
    prices = [
        {
            "asset_code": "000001.SZ",
            "price": 10.5,
            "change": 0.2,
            "change_pct": 1.94,
            "timestamp": "2026-07-10T14:30:00+08:00",
            "source": "test",
        }
    ]
    mock_use_case = _build_mock_use_case(prices=prices)
    with patch("apps.realtime.interface.views.PricePollingUseCase", return_value=mock_use_case):
        resp = client.get("/api/realtime/prices/000001.SZ/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["asset_code"] == "000001.SZ"
    assert data["price"] == 10.5
    assert data["timestamp"] == "2026-07-10T14:30:00+08:00"


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


def test_price_polling_use_case_fetches_missing_prices_from_provider():
    use_case = PricePollingUseCase.__new__(PricePollingUseCase)
    use_case.price_repository = Mock()
    use_case.price_provider = Mock()
    use_case.config = PricePollingConfig()
    use_case.service = Mock(
        price_repository=use_case.price_repository, price_provider=use_case.price_provider
    )

    now = datetime.now(UTC)
    cached_price = RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("10.50"),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=now,
        source="cache",
    )
    fetched_price = RealtimePrice(
        asset_code="600000.SH",
        asset_type=AssetType.EQUITY,
        price=Decimal("12.30"),
        change=None,
        change_pct=None,
        volume=200,
        timestamp=now,
        source="provider",
    )
    use_case.price_repository.get_latest_prices.return_value = [cached_price]
    use_case.price_provider.get_realtime_prices_batch.return_value = [fetched_price]

    prices = use_case.get_latest_prices(["000001.SZ", "600000.SH"])

    assert [item["asset_code"] for item in prices] == ["000001.SZ", "600000.SH"]
    use_case.price_provider.get_realtime_prices_batch.assert_called_once_with(["600000.SH"])
    use_case.price_repository.save_prices_batch.assert_not_called()


def test_price_polling_use_case_replaces_stale_cached_price_from_provider():
    use_case = PricePollingUseCase.__new__(PricePollingUseCase)
    use_case.price_repository = Mock()
    use_case.price_provider = Mock()
    use_case.config = PricePollingConfig()
    use_case.service = Mock(
        price_repository=use_case.price_repository,
        price_provider=use_case.price_provider,
    )
    now = datetime.now(UTC)
    stale_price = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3880.10"),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=now - timedelta(days=100),
        source="data_center",
    )
    live_price = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3804.69"),
        change=None,
        change_pct=None,
        volume=200,
        timestamp=now,
        source="tencent",
    )
    use_case.price_repository.get_latest_prices.return_value = [stale_price]
    use_case.price_provider.get_realtime_prices_batch.return_value = [live_price]

    prices = use_case.get_latest_prices(["000001.SH"])

    assert prices == [live_price.to_dict()]
    use_case.price_provider.get_realtime_prices_batch.assert_called_once_with(["000001.SH"])
    use_case.price_repository.save_prices_batch.assert_not_called()


def test_price_polling_service_rejects_stale_provider_prices_before_side_effects():
    """A stale provider observation cannot reach persistence, positions, or alerts."""

    repository = Mock()
    provider = Mock()
    watchlist = Mock()
    positions = Mock()
    watchlist.get_all_monitored_assets.return_value = ["000001.SH"]
    repository.get_latest_prices.return_value = []
    positions.update_position_prices.return_value = []
    stale = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3880.10"),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=datetime.now(UTC) - timedelta(days=30),
        source="stale_provider",
    )
    provider.get_realtime_prices_batch.return_value = [stale]
    service = PricePollingService(
        price_repository=repository,
        price_provider=provider,
        watchlist_provider=watchlist,
        position_repository=positions,
        config=PricePollingConfig(max_price_age_seconds=300),
    )

    snapshot = service.poll_and_update_prices()

    assert snapshot.prices == []
    assert snapshot.success_count == 0
    assert snapshot.failed_count == 1
    repository.save_prices_batch.assert_not_called()
    positions.update_position_prices.assert_called_once_with({})


def test_poll_single_asset_rejects_stale_provider_observation():
    """Single-asset polling applies the same freshness boundary as batch polling."""

    repository = Mock()
    provider = Mock()
    watchlist = Mock()
    repository.get_latest_price.return_value = None
    provider.get_realtime_price.return_value = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3880.10"),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=datetime.now(UTC) - timedelta(days=30),
        source="stale_provider",
    )
    service = PricePollingService(
        price_repository=repository,
        price_provider=provider,
        watchlist_provider=watchlist,
        position_repository=Mock(),
        config=PricePollingConfig(max_price_age_seconds=300),
    )

    update = service.poll_single_asset("000001.SH")

    assert update is not None
    assert update.status.value == "failed"
    assert update.new_price is None
    repository.save_price.assert_not_called()


def test_cached_monitored_prices_exclude_stale_observations():
    """Read-only movers cannot resurrect expired realtime cache rows."""

    use_case = PricePollingUseCase.__new__(PricePollingUseCase)
    use_case.price_repository = Mock()
    use_case.watchlist_provider = Mock()
    use_case.config = PricePollingConfig(max_price_age_seconds=300)
    use_case.watchlist_provider.get_all_monitored_assets.return_value = [
        "000001.SH",
        "399001.SZ",
    ]
    now = datetime.now(UTC)
    fresh = RealtimePrice(
        asset_code="399001.SZ",
        asset_type=AssetType.INDEX,
        price=Decimal("13285.80"),
        change=None,
        change_pct=Decimal("-2.73"),
        volume=200,
        timestamp=now,
        source="fresh_cache",
    )
    stale = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3880.10"),
        change=None,
        change_pct=Decimal("1.00"),
        volume=100,
        timestamp=now - timedelta(days=30),
        source="stale_cache",
    )
    use_case.price_repository.get_latest_prices.return_value = [stale, fresh]

    assert use_case.get_cached_monitored_prices() == [fresh.to_dict()]
