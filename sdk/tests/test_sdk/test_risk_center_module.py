from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_risk_center_floor_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": {"max_total_position_pct": 0.75}},
    ) as mock_request:
        result = client.risk_center.get_floor()

    args, kwargs = mock_request.call_args
    assert result == {"max_total_position_pct": 0.75}
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/floor/"
    assert kwargs == {"params": None}


def test_risk_center_update_floor_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "max_total_position_pct": 0.8,
        "force_stop_loss": True,
        "reason": "tighten portfolio exposure",
    }

    with patch.object(
        client,
        "_request",
        return_value={"data": {"id": 3, "is_active": True, **payload}},
    ) as mock_request:
        result = client.risk_center.update_floor(payload)

    args, kwargs = mock_request.call_args
    assert result == {"id": 3, "is_active": True, **payload}
    assert args[0] == "PUT"
    assert args[1] == "/api/risk-center/floor/"
    assert kwargs == {"data": None, "json": payload}


def test_risk_center_templates_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": [{"key": "moderate"}]},
    ) as mock_request:
        result = client.risk_center.list_templates()

    args, kwargs = mock_request.call_args
    assert result == [{"key": "moderate"}]
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/templates/"
    assert kwargs == {"params": None}


def test_risk_center_effective_policy_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": {"account_id": 7, "template_key": "moderate"}},
    ) as mock_request:
        result = client.risk_center.get_effective_policy(7)

    args, kwargs = mock_request.call_args
    assert result == {"account_id": 7, "template_key": "moderate"}
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/effective-policy/"
    assert kwargs == {"params": {"account_id": 7}}


def test_risk_center_account_policy_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": {"account_id": 7, "max_total_position_pct": 0.72}},
    ) as mock_request:
        result = client.risk_center.get_account_policy(7)

    args, kwargs = mock_request.call_args
    assert result == {"account_id": 7, "max_total_position_pct": 0.72}
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/account-policies/by-account/7/"
    assert kwargs == {"params": None}


def test_risk_center_account_policy_catalog_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": [{"id": 4, "account_id": 7}]},
    ) as mock_request:
        result = client.risk_center.list_account_policies()

    args, kwargs = mock_request.call_args
    assert result == [{"id": 4, "account_id": 7}]
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/account-policies/"
    assert kwargs == {"params": None}


def test_risk_center_upsert_account_policy_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "account_id": 7,
        "risk_profile": "moderate",
        "max_total_position_pct": 0.72,
        "reason": "align account policy",
    }

    with patch.object(
        client,
        "_request",
        return_value={"data": {"id": 4, **payload}},
    ) as mock_request:
        result = client.risk_center.upsert_account_policy(payload)

    args, kwargs = mock_request.call_args
    assert result == {"id": 4, **payload}
    assert args[0] == "POST"
    assert args[1] == "/api/risk-center/account-policies/"
    assert kwargs == {"data": None, "json": payload}


def test_risk_center_exceptions_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": [{"account_id": 7, "field_name": "max_total_position_pct"}]},
    ) as mock_request:
        result = client.risk_center.list_exceptions(account_id=7)

    args, kwargs = mock_request.call_args
    assert result == [{"account_id": 7, "field_name": "max_total_position_pct"}]
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/exceptions/"
    assert kwargs == {"params": {"account_id": 7}}


def test_risk_center_create_exception_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "account_id": 7,
        "field_name": "max_total_position_pct",
        "allowed_value": 0.85,
        "reason": "temporary rebalance",
        "expires_at": "2026-07-13T09:00:00+08:00",
        "is_active": True,
    }

    with patch.object(
        client,
        "_request",
        return_value={"data": {"id": 11, **payload}},
    ) as mock_request:
        result = client.risk_center.create_exception(payload)

    args, kwargs = mock_request.call_args
    assert result == {"id": 11, **payload}
    assert args[0] == "POST"
    assert args[1] == "/api/risk-center/exceptions/"
    assert kwargs == {"data": None, "json": payload}


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


def test_risk_center_daily_report_history_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value={"data": [{"report_date": "2026-06-28"}]},
    ) as mock_request:
        result = client.risk_center.list_daily_reports(
            account_id=1,
            start_date="2026-06-01",
            end_date="2026-06-28",
            limit=30,
        )

    args, kwargs = mock_request.call_args
    assert result == [{"report_date": "2026-06-28"}]
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/daily-report/"
    assert kwargs == {
        "params": {
            "account_id": 1,
            "start_date": "2026-06-01",
            "end_date": "2026-06-28",
            "limit": 30,
        }
    }

    with patch.object(
        client,
        "_request",
        return_value={"data": {"report_date": "2026-06-28"}},
    ) as mock_request:
        exact = client.risk_center.get_daily_report(1, "2026-06-28")

    args, kwargs = mock_request.call_args
    assert exact == {"report_date": "2026-06-28"}
    assert args[0] == "GET"
    assert args[1] == "/api/risk-center/daily-report/"
    assert kwargs == {"params": {"account_id": 1, "report_date": "2026-06-28"}}
