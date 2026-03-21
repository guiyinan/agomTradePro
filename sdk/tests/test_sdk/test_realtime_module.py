from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


@pytest.fixture
def client():
    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


def test_get_price_normalizes_backend_payload(client):
    mock_response = {
        "success": True,
        "asset_code": "000001.SH",
        "price": 12.34,
        "change": 0.56,
        "change_pct": 4.75,
        "timestamp": "2026-03-15T10:00:00+08:00",
    }

    with patch.object(client, "_request", return_value=mock_response):
        price = client.realtime.get_price("000001.SH")

    assert price["asset_code"] == "000001.SH"
    assert price["current_price"] == 12.34
    assert price["price_change"] == 0.56
    assert price["price_change_percent"] == 4.75
    assert price["updated_at"] == "2026-03-15T10:00:00+08:00"


def test_get_multiple_prices_uses_query_endpoint(client):
    mock_response = {
        "prices": [
            {"asset_code": "000001.SH", "price": 12.34, "change_pct": 4.75, "volume": 1000},
            {"asset_code": "399001.SZ", "price": 9.87, "change_pct": -1.25, "volume": 800},
        ]
    }

    with patch.object(client, "_request", return_value=mock_response) as mock_request:
        prices = client.realtime.get_multiple_prices(["000001.SH", "399001.SZ"])

    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/realtime/prices/"
    assert kwargs["params"] == {"assets": "000001.SH,399001.SZ"}
    assert prices["000001.SH"]["current_price"] == 12.34
    assert prices["399001.SZ"]["price_change_percent"] == -1.25


def test_get_top_gainers_and_most_active_sort_snapshot(client):
    mock_snapshot = {
        "prices": [
            {"asset_code": "A", "price": 10, "change_pct": 1.0, "volume": 100},
            {"asset_code": "B", "price": 20, "change_pct": 5.0, "volume": 50},
            {"asset_code": "C", "price": 30, "change_pct": -2.0, "volume": 500},
        ]
    }

    with patch.object(client, "_request", return_value=mock_snapshot):
        gainers = client.realtime.get_top_gainers(limit=2)
        losers = client.realtime.get_top_losers(limit=1)
        active = client.realtime.get_most_active(limit=1)

    assert [item["asset_code"] for item in gainers] == ["B", "A"]
    assert [item["asset_code"] for item in losers] == ["C"]
    assert [item["asset_code"] for item in active] == ["C"]


def test_get_market_overview_adds_compatibility_fields(client):
    mock_response = {
        "success": True,
        "timestamp": "2026-03-15T10:00:00+08:00",
        "sh_index": 3300.0,
        "sh_index_change": 10.0,
        "sh_index_change_pct": 0.3,
        "up_count": 3000,
        "down_count": 1200,
        "flat_count": 100,
        "limit_up_count": 35,
        "limit_down_count": 2,
        "total_value": 123456789.0,
    }

    with patch.object(client, "_request", return_value=mock_response):
        overview = client.realtime.get_market_overview()

    assert overview["market_status"] == "open"
    assert overview["last_update"] == "2026-03-15T10:00:00+08:00"
    assert overview["market_summary"]["advancing"] == 3000
    assert overview["indices"][0]["name"] == "Shanghai Index"
