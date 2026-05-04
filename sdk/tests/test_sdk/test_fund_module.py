from datetime import date
from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


@pytest.fixture
def client():
    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


def test_get_fund_detail_unwraps_fund_payload_and_normalizes_code(client):
    payload = {
        "success": True,
        "fund": {
            "fund_code": "000001",
            "fund_name": "华夏成长",
            "fund_type": "股票型",
        },
    }

    with patch.object(client, "_request", return_value=payload) as mock_request:
        detail = client.fund.get_fund_detail("000001.OF")

    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/fund/info/000001/"
    assert kwargs["params"] is None
    assert detail["fund_code"] == "000001"
    assert detail["fund_type"] == "股票型"


def test_analyze_fund_uses_report_date_query_param(client):
    payload = {
        "success": True,
        "fund_code": "000001",
        "style_weights": {"成长": 0.6},
    }

    with patch.object(client, "_request", return_value=payload) as mock_request:
        result = client.fund.analyze_fund("000001.OF", report_date=date(2024, 12, 31))

    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/fund/style/000001/"
    assert kwargs["params"] == {"report_date": "2024-12-31"}
    assert result["fund_code"] == "000001"


def test_get_nav_history_reads_nav_data_payload(client):
    payload = {
        "success": True,
        "fund_code": "000001",
        "count": 1,
        "nav_data": [{"nav_date": "2024-12-31", "unit_nav": "1.2345"}],
    }

    with patch.object(client, "_request", return_value=payload) as mock_request:
        nav_history = client.fund.get_nav_history(
            "000001.OF",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            limit=50,
        )

    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/fund/nav/000001/"
    assert kwargs["params"] == {
        "limit": 50,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
    }
    assert nav_history == [{"nav_date": "2024-12-31", "unit_nav": "1.2345"}]


def test_get_holdings_uses_report_date_alias_and_unwraps_holdings(client):
    payload = {
        "success": True,
        "fund_code": "000001",
        "holdings": [{"stock_code": "600519.SH", "holding_ratio": 0.1}],
    }

    with patch.object(client, "_request", return_value=payload) as mock_request:
        holdings = client.fund.get_holdings("000001.OF", as_of_date=date(2024, 9, 30))

    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/fund/holding/000001/"
    assert kwargs["params"] == {"report_date": "2024-09-30"}
    assert holdings == [{"stock_code": "600519.SH", "holding_ratio": 0.1}]


def test_get_performance_normalizes_fund_code_and_unwraps_payload(client):
    payload = {
        "success": True,
        "fund_code": "000001",
        "performance": {"total_return": 0.12},
    }

    with patch.object(client, "_request", return_value=payload) as mock_request:
        performance = client.fund.get_performance("000001.OF", period="1m")

    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/fund/performance/calculate/"
    assert kwargs["json"]["fund_code"] == "000001"
    assert performance == {"total_return": 0.12}


def test_get_performance_anchors_period_to_latest_local_nav_date(client):
    payload = {
        "success": True,
        "fund_code": "000024",
        "performance": {"total_return": 0.21},
    }

    with patch.object(
        client.fund,
        "get_nav_history",
        return_value=[
            {"nav_date": "2024-01-15", "unit_nav": "1.0000"},
            {"nav_date": "2024-12-31", "unit_nav": "1.2345"},
        ],
    ):
        with patch.object(client, "_request", return_value=payload) as mock_request:
            performance = client.fund.get_performance("000024", period="1y")

    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/fund/performance/calculate/"
    assert kwargs["json"]["fund_code"] == "000024"
    assert kwargs["json"]["end_date"] == "2024-12-31"
    assert kwargs["json"]["start_date"] == "2024-01-01"
    assert performance == {"total_return": 0.21}


def test_get_recommendations_can_filter_rank_results_by_fund_type(client):
    ranked_funds = [
        {"fund_code": "000001", "total_score": 92.0},
        {"fund_code": "000002", "total_score": 88.0},
    ]

    with patch.object(client.fund, "rank_funds", return_value=ranked_funds):
        with patch.object(
            client.fund,
            "get_fund_detail",
            side_effect=[
                {"fund_code": "000001", "fund_type": "股票型"},
                {"fund_code": "000002", "fund_type": "债券型"},
            ],
        ):
            recommendations = client.fund.get_recommendations(
                regime="Recovery",
                fund_type="股票型",
                limit=5,
            )

    assert recommendations == [{"fund_code": "000001", "total_score": 92.0}]
