"""SDK contracts for the persisted read candidates unlocked by route alignment."""

from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_aligned_read_candidates_use_canonical_http_contracts() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test-token")
    responses = [
        {"results": [{"stock_code": "000001.SZ", "period_type": "annual"}]},
        {"score": {"fund_code": "000001", "total_score": 88.0}},
        {"score": {"sector_name": "银行", "total_score": 80.0}},
        {"results": [{"sector_code": "801780", "change_percent": 1.2}]},
        {"strategy_id": 1, "execution_count": 2},
        {"results": [{"asset_code": "510300.SH", "status": "generated"}]},
        {"results": [{"asset_code": "510300.SH", "quantity": "10"}]},
        {"config_name": "balanced", "holdings": []},
    ]

    with patch.object(client, "_request", side_effect=responses) as request:
        financials = client.equity.get_financials("000001.SZ")
        fund_score = client.fund.get_fund_score("000001.OF")
        sector_score = client.sector.get_sector_score("银行")
        sector_performance = client.realtime.get_sector_performance()
        performance = client.strategy.get_strategy_performance(1)
        signals = client.strategy.get_strategy_signals(1)
        positions = client.strategy.get_strategy_positions(1)
        portfolio = client.factor.get_portfolio("balanced")

    assert financials[0]["period_type"] == "annual"
    assert fund_score["total_score"] == 88.0
    assert sector_score["total_score"] == 80.0
    assert sector_performance[0]["sector_code"] == "801780"
    assert performance["execution_count"] == 2
    assert signals[0]["status"] == "generated"
    assert positions[0]["asset_code"] == "510300.SH"
    assert portfolio == {"config_name": "balanced", "holdings": []}
    assert [call.args[:2] for call in request.call_args_list] == [
        ("GET", "/api/equity/financials/000001.SZ/"),
        ("GET", "/api/fund/score/000001/"),
        ("GET", "/api/sector/score/银行/"),
        ("GET", "/api/realtime/sector-performance/"),
        ("GET", "/api/strategy/strategies/1/performance/"),
        ("GET", "/api/strategy/strategies/1/signals/"),
        ("GET", "/api/strategy/strategies/1/positions/"),
        ("GET", "/api/factor/portfolio/"),
    ]


def test_governed_composite_reads_use_canonical_sdk_contracts() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test-token")
    responses = [
        {"success": True, "stocks": [{"code": "000001.SZ", "score": 88.0}]},
        {
            "success": True,
            "regime": "Recovery",
            "stock_codes": ["000001.SZ"],
            "screening_criteria": {"min_roe": 15},
        },
        {"success": True, "stocks": [{"code": "000001.SZ", "score": 88.0}]},
        {"success": True, "stock_code": "000001.SZ", "current_pe": 10.0},
        {"funds": [{"fund_code": "000001", "total_score": 90.0}]},
        {"score": {"sector_name": "银行", "total_score": 80.0}},
        {
            "top_sectors": [
                {"sector_name": "银行", "total_score": 80.0},
                {"sector_name": "医药", "total_score": 75.0},
            ]
        },
    ]

    with patch.object(client, "_request", side_effect=responses) as request:
        score = client.equity.get_stock_score("000001.SZ")
        recommendations = client.equity.get_recommendations(regime="Recovery", limit=10)
        analysis = client.equity.analyze_stock("000001.SZ")
        funds = client.fund.list_funds(min_score=80, limit=10)
        sector_analysis = client.sector.analyze_sector("银行")
        sector_comparison = client.sector.compare_sectors(["银行", "医药"])

    assert score["overall_score"] == 88.0
    assert recommendations == [
        {
            "code": "000001.SZ",
            "regime": "Recovery",
            "screening_criteria": {"min_roe": 15},
        }
    ]
    assert analysis["valuation"]["current_pe"] == 10.0
    assert funds == [{"fund_code": "000001", "total_score": 90.0}]
    assert sector_analysis["analysis"]["total_score"] == 80.0
    assert sector_comparison["医药"]["total_score"] == 75.0
    assert [call.args[:2] for call in request.call_args_list] == [
        ("GET", "/api/equity/pool/"),
        ("POST", "/api/equity/screen/"),
        ("GET", "/api/equity/pool/"),
        ("GET", "/api/equity/valuation/000001.SZ/"),
        ("GET", "/api/fund/rank/"),
        ("GET", "/api/sector/score/银行/"),
        ("GET", "/api/sector/rotation/"),
    ]
