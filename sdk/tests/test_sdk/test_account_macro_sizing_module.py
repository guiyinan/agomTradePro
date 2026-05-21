from unittest.mock import patch

from agomtradepro import AgomTradeProClient


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
