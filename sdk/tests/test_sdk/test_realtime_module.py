from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProAPIError, AgomTradeProClient, ServerError


def _usable_top_movers_payload(results: list[dict[str, object]]) -> dict[str, object]:
    """Build a complete success envelope required by the legacy list projection."""

    return {
        "results": results,
        "count": len(results),
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": len(results),
        "qualified": len(results),
        "unavailable": 0,
        "rankable": len(results),
        "unrankable": 0,
        "outcome": "success",
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }


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

    with patch.object(client, "_request", return_value=mock_response) as mock_request:
        price = client.realtime.get_price("000001.SH")

    mock_request.assert_called_once_with(
        "GET",
        "/api/realtime/prices/000001.SH/",
        params=None,
    )
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


def test_price_history_delegates_to_data_center_owner(client):
    payload = {"data": [{"asset_code": "000001.SH", "freq": "1d", "close": 12.3}]}

    with (
        patch.object(
            client.data_center,
            "get_price_history",
            return_value=payload,
        ) as get_history,
        patch.object(client, "_request") as request,
    ):
        result = client.realtime.get_price_history("000001.SH", period="1d", limit=30)

    assert result == payload["data"]
    get_history.assert_called_once_with(
        asset_code="000001.SH",
        freq="1d",
        limit=30,
    )
    request.assert_not_called()


def test_get_top_gainers_and_most_active_sort_snapshot(client):
    mock_snapshot = {
        "prices": [
            {"asset_code": "A", "price": 10, "change_pct": 1.0, "volume": 100},
            {"asset_code": "B", "price": 20, "change_pct": 5.0, "volume": 50},
            {"asset_code": "C", "price": 30, "change_pct": -2.0, "volume": 500},
        ]
    }

    with patch.object(
        client,
        "_request",
        side_effect=[
            _usable_top_movers_payload([mock_snapshot["prices"][1], mock_snapshot["prices"][0]]),
            _usable_top_movers_payload([mock_snapshot["prices"][2]]),
            mock_snapshot,
        ],
    ):
        gainers = client.realtime.get_top_gainers(limit=2)
        losers = client.realtime.get_top_losers(limit=1)
        active = client.realtime.get_most_active(limit=1)

    assert [item["asset_code"] for item in gainers] == ["B", "A"]
    assert [item["asset_code"] for item in losers] == ["C"]
    assert [item["asset_code"] for item in active] == ["C"]


def test_get_top_movers_uses_cached_read_endpoint(client):
    response = _usable_top_movers_payload(
        [
            {"asset_code": "B", "price": 20, "change_pct": 5.0},
            {"asset_code": "A", "price": 10, "change_pct": 1.0},
        ]
    )
    with patch.object(client, "_request", return_value=response) as request:
        movers = client.realtime.get_top_movers(direction="up", limit=2)

    assert [item["asset_code"] for item in movers] == ["B", "A"]
    request.assert_called_once_with(
        "GET",
        "/api/realtime/top-movers/",
        params={"direction": "up", "limit": 2},
    )


@pytest.mark.parametrize(
    "restriction",
    [
        {
            "scope_available": True,
            "outcome": "partial",
            "is_reliable": False,
            "is_stale": None,
            "must_not_use_for_decision": True,
            "requested": 2,
            "qualified": 1,
            "unavailable": 1,
            "rankable": 1,
            "unrankable": 0,
            "blocked_reason": "monitored_cached_prices_incomplete",
        },
        {
            "scope_available": True,
            "outcome": "partial",
            "is_reliable": False,
            "is_stale": False,
            "must_not_use_for_decision": True,
            "requested": 2,
            "qualified": 2,
            "unavailable": 0,
            "rankable": 1,
            "unrankable": 1,
            "blocked_reason": "monitored_top_movers_change_pct_unavailable",
        },
        {
            "scope_available": True,
            "outcome": "blocked",
            "is_reliable": False,
            "is_stale": None,
            "must_not_use_for_decision": True,
            "requested": 0,
            "qualified": 0,
            "unavailable": 0,
            "rankable": 0,
            "unrankable": 0,
            "blocked_reason": "monitored_asset_scope_empty",
            "results": [],
            "count": 0,
        },
        {
            "scope_available": False,
            "outcome": "blocked",
            "is_reliable": False,
            "is_stale": None,
            "must_not_use_for_decision": True,
            "requested": None,
            "qualified": None,
            "unavailable": None,
            "rankable": None,
            "unrankable": None,
            "blocked_reason": "monitored_price_scope_unavailable",
        },
        {
            "scope_available": True,
            "outcome": "success",
            "is_reliable": True,
            "is_stale": False,
            "must_not_use_for_decision": False,
            "requested": 1,
            "qualified": 1,
            "unavailable": 0,
            "rankable": None,
            "unrankable": None,
            "blocked_reason": "",
        },
        {"outcome": "future-state", "must_not_use_for_decision": False},
        {"outcome": None, "must_not_use_for_decision": False},
    ],
    ids=[
        "partial-price-scope",
        "partial-ranking-metric",
        "resolved-empty-blocked",
        "unknown-scope",
        "unknown-ranking-counts",
        "future-outcome",
        "missing-outcome",
    ],
)
def test_get_top_movers_rejects_restricted_or_unknown_list_projection(
    client,
    restriction: dict[str, object],
) -> None:
    response: dict[str, object] = {
        **_usable_top_movers_payload([{"asset_code": "A", "price": 10.0}]),
        **restriction,
    }
    with patch.object(client, "_request", return_value=response):
        with pytest.raises(AgomTradeProAPIError) as raised:
            client.realtime.get_top_movers()

    assert raised.value.code == "realtime_top_movers_not_decision_usable"
    assert raised.value.response == response
    assert "get_top_movers_payload()" in str(raised.value)


def test_get_top_movers_payload_preserves_partial_scope_evidence(client) -> None:
    response: dict[str, object] = {
        **_usable_top_movers_payload([{"asset_code": "A", "price": 10.0}]),
        "requested": 4,
        "qualified": 1,
        "unavailable": 3,
        "rankable": 1,
        "unrankable": 0,
        "outcome": "partial",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_cached_prices_incomplete",
    }
    with patch.object(client, "_request", return_value=response) as request:
        payload = client.realtime.get_top_movers_payload(direction="down", limit=5)

    assert payload["requested"] == 4
    assert payload["qualified"] == 1
    assert payload["unavailable"] == 3
    assert payload["rankable"] == 1
    assert payload["unrankable"] == 0
    assert payload["outcome"] == "partial"
    assert payload["must_not_use_for_decision"] is True
    assert payload["results"][0]["current_price"] == 10.0
    request.assert_called_once_with(
        "GET",
        "/api/realtime/top-movers/",
        params={"direction": "down", "limit": 5},
    )


def test_get_top_movers_payload_retains_resolved_empty_blocked_scope(client) -> None:
    response: dict[str, object] = {
        "results": [],
        "count": 0,
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": 0,
        "qualified": 0,
        "unavailable": 0,
        "rankable": 0,
        "unrankable": 0,
        "outcome": "blocked",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_asset_scope_empty",
    }
    with patch.object(client, "_request", return_value=response):
        payload = client.realtime.get_top_movers_payload()

    assert payload == response
    assert payload["outcome"] == "blocked"
    assert payload["must_not_use_for_decision"] is True


def test_get_top_movers_rejects_missing_completeness_evidence(client) -> None:
    incomplete = {
        "results": [{"asset_code": "A", "price": 10.0}],
        "count": 1,
        "scope_available": True,
        "outcome": "success",
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "requested": 1,
        "qualified": 1,
        "unavailable": 0,
        "rankable": 1,
        "unrankable": 0,
        "blocked_reason": "",
    }
    with patch.object(client, "_request", return_value=incomplete):
        with pytest.raises(AgomTradeProAPIError) as raised:
            client.realtime.get_top_movers()

    assert raised.value.code == "realtime_top_movers_not_decision_usable"
    assert raised.value.response == incomplete


def test_get_top_movers_payload_keeps_http_503_server_response(client) -> None:
    blocked = {
        "outcome": "blocked",
        "scope_available": False,
        "requested": None,
        "qualified": None,
        "unavailable": None,
        "rankable": None,
        "unrankable": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_price_scope_unavailable",
    }
    server_error = ServerError(
        status_code=503,
        response=blocked,
    )
    with patch.object(client, "_request", side_effect=server_error):
        with pytest.raises(ServerError) as raised:
            client.realtime.get_top_movers_payload()

    assert raised.value.status_code == 503
    assert raised.value.response == blocked


@pytest.mark.parametrize("legacy_method", ["get_top_gainers", "get_top_losers"])
def test_legacy_top_mover_aliases_reject_partial_scope(
    client,
    legacy_method: str,
) -> None:
    partial: dict[str, object] = {
        **_usable_top_movers_payload([{"asset_code": "A", "price": 10.0}]),
        "requested": 4,
        "qualified": 1,
        "unavailable": 3,
        "rankable": 1,
        "unrankable": 0,
        "outcome": "partial",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_cached_prices_incomplete",
    }
    with patch.object(client, "_request", return_value=partial):
        with pytest.raises(AgomTradeProAPIError) as raised:
            getattr(client.realtime, legacy_method)()

    assert raised.value.code == "realtime_top_movers_not_decision_usable"
    assert raised.value.response == partial


def test_get_top_movers_rejects_inconsistent_success_row_count(client) -> None:
    inconsistent: dict[str, object] = {
        **_usable_top_movers_payload([]),
        "requested": 1,
        "qualified": 1,
        "unavailable": 0,
        "rankable": 1,
        "unrankable": 0,
        "count": 0,
        "outcome": "success",
    }
    with patch.object(client, "_request", return_value=inconsistent):
        with pytest.raises(AgomTradeProAPIError) as raised:
            client.realtime.get_top_movers()

    assert raised.value.code == "realtime_top_movers_not_decision_usable"
    assert raised.value.response == inconsistent


@pytest.mark.parametrize("legacy_method", ["get_top_movers", "get_top_gainers", "get_top_losers"])
def test_legacy_top_mover_methods_preserve_unknown_scope_server_error(
    client,
    legacy_method: str,
) -> None:
    blocked: dict[str, object] = {
        "results": [],
        "count": 0,
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": False,
        "requested": None,
        "qualified": None,
        "unavailable": None,
        "rankable": None,
        "unrankable": None,
        "outcome": "blocked",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_price_scope_unavailable",
    }
    server_error = ServerError(status_code=503, response=blocked)
    with patch.object(client, "_request", side_effect=server_error):
        with pytest.raises(ServerError) as raised:
            if legacy_method == "get_top_movers":
                client.realtime.get_top_movers()
            else:
                getattr(client.realtime, legacy_method)()

    assert raised.value.status_code == 503
    assert raised.value.response == blocked


def test_get_market_summary_endpoint_and_overview_compatibility_fields(client):
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

    with patch.object(client, "_request", return_value=mock_response) as mock_request:
        summary = client.realtime.get_market_summary()
        overview = client.realtime.get_market_overview()

    assert summary == mock_response
    assert mock_request.call_args_list[0].args == (
        "GET",
        "/api/realtime/market-summary/",
    )
    assert mock_request.call_args_list[0].kwargs == {"params": None}
    assert overview["market_status"] == "open"
    assert overview["last_update"] == "2026-03-15T10:00:00+08:00"
    assert overview["market_summary"]["advancing"] == 3000
    assert overview["indices"][0]["name"] == "Shanghai Index"


def test_price_alert_methods_use_canonical_owner_scoped_paths(client):
    responses = [
        {"results": [{"id": 1, "status": "active"}], "count": 1},
        {"id": 2, "asset_code": "510300.SH"},
        {"id": 2, "status": "active"},
        {"id": 2, "status": "inactive"},
        {},
    ]
    with patch.object(client, "_request", side_effect=responses) as request:
        assert client.realtime.list_alerts(status="active", limit=10) == [
            {"id": 1, "status": "active"}
        ]
        client.realtime.create_alert("510300.SH", "cross_up", 3.5, "突破")
        client.realtime.get_alert(2)
        client.realtime.update_alert(2, status="inactive")
        client.realtime.delete_alert(2)

    assert request.call_args_list[0].args == ("GET", "/api/realtime/alerts/")
    assert request.call_args_list[1].args == ("POST", "/api/realtime/alerts/")
    assert request.call_args_list[1].kwargs["json"] == {
        "asset_code": "510300.SH",
        "condition": "cross_up",
        "threshold": "3.5",
        "message": "突破",
    }
    assert request.call_args_list[2].args == ("GET", "/api/realtime/alerts/2/")
    assert request.call_args_list[3].args == ("PATCH", "/api/realtime/alerts/2/")
    assert request.call_args_list[3].kwargs["json"] == {"status": "inactive"}
    assert request.call_args_list[4].args == ("DELETE", "/api/realtime/alerts/2/")


def test_price_subscription_methods_use_canonical_paths(client):
    responses = [
        {"id": 1, "asset_code": "510300.SH"},
        {"results": [{"id": 1, "asset_code": "510300.SH"}], "count": 1},
        {},
    ]
    with patch.object(client, "_request", side_effect=responses) as request:
        client.realtime.subscribe_price("510300.SH")
        assert client.realtime.get_subscriptions() == [{"id": 1, "asset_code": "510300.SH"}]
        client.realtime.unsubscribe_price("510300.SH")

    assert request.call_args_list[0].args == (
        "POST",
        "/api/realtime/subscriptions/",
    )
    assert request.call_args_list[0].kwargs["json"] == {"asset_code": "510300.SH"}
    assert request.call_args_list[1].args == (
        "GET",
        "/api/realtime/subscriptions/",
    )
    assert request.call_args_list[2].args == (
        "DELETE",
        "/api/realtime/subscriptions/510300.SH/",
    )
