from unittest.mock import patch

from agomtradepro import AgomTradeProClient, NotFoundError


def test_factor_catalog_methods_hit_canonical_get_endpoints() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

    with patch.object(
        client,
        "_request",
        side_effect=[
            [{"code": "pe_ttm", "category": "value"}],
            [{"name": "balanced", "universe": "all_a"}],
        ],
    ) as mock_request:
        factors = client.factor.get_all_factors()
        configs = client.factor.get_all_configs()

    assert factors == [{"code": "pe_ttm", "category": "value"}]
    assert configs == [{"name": "balanced", "universe": "all_a"}]
    assert mock_request.call_args_list[0].args == (
        "GET",
        "/api/factor/all-factors/",
    )
    assert mock_request.call_args_list[0].kwargs == {"params": None}
    assert mock_request.call_args_list[1].args == (
        "GET",
        "/api/factor/all-configs/",
    )
    assert mock_request.call_args_list[1].kwargs == {"params": None}


def test_get_top_stocks_uses_canonical_pure_compute_endpoint() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

    with patch.object(
        client,
        "_request",
        return_value={
            "total_stocks": 1,
            "stocks": [{"stock_code": "600000.SH", "composite_score": 88.5}],
        },
    ) as mock_request:
        result = client.factor.get_top_stocks(
            {
                "value": "high",
                "quality": "medium",
                "growth": "low",
                "momentum": "high",
            },
            top_n=10,
        )

    assert result["stocks"][0]["stock_code"] == "600000.SH"
    assert mock_request.call_args.args == (
        "POST",
        "/api/factor/top-stocks/",
    )
    assert mock_request.call_args.kwargs == {
        "data": None,
        "json": {
            "factor_preferences": {
                "value": "high",
                "quality": "medium",
                "growth": "low",
                "momentum": "high",
            },
            "top_n": 10,
        }
    }


def test_explain_stock_by_focus_uses_stable_weights_and_canonical_endpoint() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

    with patch.object(
        client,
        "post",
        return_value={
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "composite_score": 82.5,
            "percentile_rank": 0.0,
            "factor_breakdown": {},
            "category_breakdown": {},
        },
    ) as mock_post:
        result = client.factor.explain_stock_by_focus(
            "600000.SH",
            focus="quality",
        )

    assert result["stock_name"] == "浦发银行"
    mock_post.assert_called_once_with(
        "/api/factor/explain-stock/",
        json={
            "stock_code": "600000.SH",
            "factor_weights": {
                "roe": 0.3,
                "roa": 0.2,
                "debt_ratio": -0.2,
                "current_ratio": 0.15,
                "gross_margin": 0.15,
            },
        },
    )


def test_get_portfolio_preserves_none_contract_for_missing_holdings() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

    with patch.object(client, "_request", side_effect=NotFoundError()) as request:
        result = client.factor.get_portfolio("missing-config")

    assert result is None
    request.assert_called_once_with(
        "GET",
        "/api/factor/portfolio/",
        params={"config_name": "missing-config"},
    )
