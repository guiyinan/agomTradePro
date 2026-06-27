from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_risk_center_pre_trade_check_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "account_id": 1,
        "symbol": "000001.SZ",
        "side": "buy",
        "quantity": 100,
        "price": 10.0,
        "account_equity": 100000.0,
        "total_position_value": 50000.0,
        "cash_balance": 50000.0,
    }

    with patch.object(client, "_request", return_value={"data": {"passed": True}}) as mock_request:
        result = client.risk_center.check_pre_trade(payload)

    args, kwargs = mock_request.call_args
    assert result == {"passed": True}
    assert args[0] == "POST"
    assert args[1] == "/api/risk-center/pre-trade-check/"
    assert kwargs == {"data": None, "json": payload}
