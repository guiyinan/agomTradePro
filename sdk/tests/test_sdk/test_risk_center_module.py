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


def test_risk_center_post_investment_check_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "account_id": 1,
        "account_equity": 100000.0,
        "cash_balance": 20000.0,
        "positions": [
            {
                "symbol": "000001.SZ",
                "market_value": 30000.0,
                "unrealized_pnl_pct": -0.05,
            }
        ],
    }

    with patch.object(client, "_request", return_value={"data": {"status": "ok"}}) as mock_request:
        result = client.risk_center.check_post_investment(payload)

    args, kwargs = mock_request.call_args
    assert result == {"status": "ok"}
    assert args[0] == "POST"
    assert args[1] == "/api/risk-center/post-investment-check/"
    assert kwargs == {"data": None, "json": payload}


def test_risk_center_daily_report_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "account_id": 1,
        "report_date": "2026-06-28",
        "account_equity": 100000.0,
        "positions": [],
    }

    with patch.object(
        client,
        "_request",
        return_value={"data": {"risk_daily_report": {"status": "ok"}}},
    ) as mock_request:
        result = client.risk_center.generate_daily_report(payload)

    args, kwargs = mock_request.call_args
    assert result == {"risk_daily_report": {"status": "ok"}}
    assert args[0] == "POST"
    assert args[1] == "/api/risk-center/daily-report/"
    assert kwargs == {"data": None, "json": payload}
