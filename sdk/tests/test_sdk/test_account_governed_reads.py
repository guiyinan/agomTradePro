"""SDK contracts for governed Account read capabilities."""

from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_list_portfolio_records_uses_canonical_portfolio_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 7, "name": "Core"}]
    with patch.object(
        client,
        "_request",
        return_value={"results": expected, "next": None},
    ) as mock_request:
        result = client.account.list_portfolio_records(limit=25)

    assert result == expected
    mock_request.assert_called_once_with(
        "GET",
        "/api/account/portfolios/",
        params={"limit": 25, "page": 1},
    )


def test_get_portfolio_record_uses_canonical_portfolio_detail_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {"id": 7, "name": "Core"}
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.account.get_portfolio_record(7)

    assert result == expected
    mock_request.assert_called_once_with(
        "GET",
        "/api/account/portfolios/7/",
        params=None,
    )


def test_list_position_records_uses_read_only_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 11, "portfolio": 7, "asset_code": "510300.SH"}]
    with patch.object(
        client,
        "_request",
        return_value={"results": expected, "next": None},
    ) as mock_request:
        result = client.account.list_position_records(
            portfolio_id=7,
            asset_code="510300.SH",
            include_closed=True,
            limit=20,
        )

    assert result == expected
    mock_request.assert_called_once_with(
        "GET",
        "/api/account/positions/read-only/",
        params={
            "portfolio_id": 7,
            "asset_code": "510300.SH",
            "include_closed": True,
            "limit": 20,
            "page": 1,
        },
    )


def test_list_transaction_records_uses_canonical_transaction_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 21, "portfolio": 7, "asset_code": "510300.SH"}]
    with patch.object(
        client,
        "_request",
        return_value={"results": expected, "next": None},
    ) as mock_request:
        result = client.account.list_transaction_records(portfolio_id=7, limit=30)

    assert result == expected
    mock_request.assert_called_once_with(
        "GET",
        "/api/account/transactions/",
        params={"limit": 30, "page": 1},
    )


def test_list_capital_flow_records_uses_canonical_capital_flow_endpoint():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 31, "portfolio": 7, "flow_type": "deposit"}]
    with patch.object(
        client,
        "_request",
        return_value={"results": expected, "next": None},
    ) as mock_request:
        result = client.account.list_capital_flow_records(portfolio_id=7, limit=40)

    assert result == expected
    mock_request.assert_called_once_with(
        "GET",
        "/api/account/capital-flows/",
        params={"limit": 40, "page": 1},
    )
