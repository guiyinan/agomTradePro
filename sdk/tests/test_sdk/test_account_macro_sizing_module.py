from unittest.mock import patch

from agomtradepro import AgomTradeProClient
from agomtradepro.types import Position


def test_get_macro_sizing_config_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(
        client,
        "_request",
        return_value={"version": 3, "market_temperature_hot_factor": 0.82},
    ) as mock_request:
        payload = client.account.get_macro_sizing_config()

    assert payload["version"] == 3
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/account/macro-sizing-config/"
    assert kwargs == {"params": None}


def test_update_macro_sizing_config_patch_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {"market_temperature_hot_factor": 0.8}
    with patch.object(client, "_request", return_value={"version": 4, **payload}) as mock_request:
        result = client.account.update_macro_sizing_config(payload, partial=True)

    assert result["market_temperature_hot_factor"] == 0.8
    args, kwargs = mock_request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "/api/account/macro-sizing-config/"
    assert kwargs == {"data": None, "json": payload}


def test_update_macro_sizing_config_put_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {"warning_factor": 0.45}
    with patch.object(client, "_request", return_value={"version": 5, **payload}) as mock_request:
        result = client.account.update_macro_sizing_config(payload, partial=False)

    assert result["warning_factor"] == 0.45
    args, kwargs = mock_request.call_args
    assert args[0] == "PUT"
    assert args[1] == "/api/account/macro-sizing-config/"
    assert kwargs == {"data": None, "json": payload}


def test_get_positions_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(
        client,
        "_request",
        return_value={
            "results": [
                {
                    "asset_code": "510300.SH",
                    "shares": 200,
                    "avg_cost": "3.80",
                    "current_price": "3.91",
                    "market_value": "782.00",
                    "unrealized_pnl": "22.00",
                }
            ]
        },
    ) as mock_request:
        positions = client.account.get_positions(
            portfolio_id=7,
            asset_code="510300.SH",
            limit=20,
        )

    assert positions == [
        Position(
            asset_code="510300.SH",
            quantity=200.0,
            avg_cost=3.8,
            current_price=3.91,
            market_value=782.0,
            profit_loss=22.0,
        )
    ]
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/account/positions/read-only/"
    assert kwargs == {
        "params": {
            "include_closed": False,
            "limit": 20,
            "page": 1,
            "portfolio_id": 7,
            "asset_code": "510300.SH",
        }
    }


def test_create_position_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(
        client,
        "_request",
        return_value={
            "asset_code": "510300.SH",
            "shares": 100,
            "avg_cost": "3.80",
            "current_price": "3.80",
            "market_value": "380.00",
            "unrealized_pnl": "0.00",
        },
    ) as mock_request:
        position = client.account.create_position(
            portfolio_id=7,
            asset_code="510300.SH",
            quantity=100,
            price=3.8,
        )

    assert position == Position(
        asset_code="510300.SH",
        quantity=100.0,
        avg_cost=3.8,
        current_price=3.8,
        market_value=380.0,
        profit_loss=0.0,
    )
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/account/positions/"
    assert kwargs == {
        "data": None,
        "json": {
            "portfolio": 7,
            "asset_code": "510300.SH",
            "shares": 100,
            "avg_cost": 3.8,
            "current_price": 3.8,
            "source": "manual",
            "asset_class": "equity",
            "region": "CN",
            "cross_border": "domestic",
        },
    }


def test_get_portfolio_statistics_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {
        "total_value": "100000.00",
        "position_count": 3,
        "net_capital_flow": "50000.00",
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.account.get_portfolio_statistics(7)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/account/portfolios/7/statistics/"
    assert kwargs == {"params": None}


def test_get_trading_cost_configs_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 11, "portfolio": 7, "commission_rate": 0.00025}]
    with patch.object(
        client,
        "_request",
        return_value={"results": expected},
    ) as mock_request:
        result = client.account.get_trading_cost_configs(limit=25)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/account/trading-cost-configs/"
    assert kwargs == {"params": {"limit": 25}}


def test_calculate_trading_cost_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {
        "commission": 5.0,
        "stamp_duty": 10.0,
        "transfer_fee": 0.2,
        "total": 15.2,
    }
    with patch.object(
        client,
        "_request",
        return_value={"success": True, "data": expected},
    ) as mock_request:
        result = client.account.calculate_trading_cost(
            config_id=11,
            action="sell",
            amount=10000.0,
            is_shanghai=True,
        )

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/account/trading-cost-configs/11/calculate/"
    assert kwargs == {
        "data": None,
        "json": {
            "action": "sell",
            "amount": 10000.0,
            "is_shanghai": True,
        },
    }
