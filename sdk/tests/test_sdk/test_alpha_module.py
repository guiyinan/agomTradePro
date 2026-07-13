from unittest.mock import patch

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import ConflictError


def test_get_factor_exposure_uses_remote_api_contract() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    response = {
        "success": True,
        "stock_code": "000001.SH",
        "trade_date": "2026-02-05",
        "provider": "simple",
        "factors": {"roe": 0.12},
    }
    with patch.object(client, "_request", return_value=response) as mock_request:
        result = client.alpha.get_factor_exposure("000001.SH", "2026-02-05", "simple")

    assert result == response
    mock_request.assert_called_once_with(
        "GET",
        "/api/alpha/factor-exposure/000001.SH/",
        params={"provider": "simple", "trade_date": "2026-02-05"},
    )


def test_get_factor_exposure_omits_trade_date_when_not_supplied() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    with patch.object(client, "_request", return_value={"factors": {}}) as mock_request:
        client.alpha.get_factor_exposure("000001.SH", provider="simple")

    mock_request.assert_called_once_with(
        "GET",
        "/api/alpha/factor-exposure/000001.SH/",
        params={"provider": "simple"},
    )


def test_alpha_ops_methods_hit_expected_endpoints() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

    with patch.object(client, "_request", return_value={"ok": True}) as mock_request:
        client.alpha.get_ops_inference_overview()
        args, kwargs = mock_request.call_args
        assert args == ("GET", "/api/alpha/ops/inference/overview/")
        assert kwargs["params"] is None

        client.alpha.get_ops_qlib_data_overview()
        args, kwargs = mock_request.call_args
        assert args == ("GET", "/api/alpha/ops/qlib-data/overview/")
        assert kwargs["params"] is None

        client.alpha.trigger_ops_inference(
            mode="portfolio_scoped",
            trade_date="2026-04-28",
            top_n=15,
            portfolio_id=8,
            pool_mode="market",
        )
        args, kwargs = mock_request.call_args
        assert args == ("POST", "/api/alpha/ops/inference/trigger/")
        assert kwargs["json"] == {
            "mode": "portfolio_scoped",
            "trade_date": "2026-04-28",
            "top_n": 15,
            "portfolio_id": 8,
            "pool_mode": "market",
        }

        client.alpha.refresh_ops_qlib_data(
            mode="scoped_codes",
            target_date="2026-04-28",
            lookback_days=120,
            portfolio_ids=[8, 9],
            all_active_portfolios=False,
            pool_mode="price_covered",
        )
        args, kwargs = mock_request.call_args
        assert args == ("POST", "/api/alpha/ops/qlib-data/refresh/")
        assert kwargs["json"] == {
            "mode": "scoped_codes",
            "target_date": "2026-04-28",
            "lookback_days": 120,
            "portfolio_ids": [8, 9],
            "all_active_portfolios": False,
            "pool_mode": "price_covered",
        }


def test_alpha_ops_write_methods_return_conflict_payload() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    conflict_payload = {
        "success": False,
        "error": "inference already running",
        "task_id": "task-123",
    }

    with patch.object(
        client,
        "_request",
        side_effect=ConflictError(response=conflict_payload),
    ):
        inference_result = client.alpha.trigger_ops_inference(
            mode="general",
            trade_date="2026-04-28",
            universe_id="csi300",
        )
        qlib_result = client.alpha.refresh_ops_qlib_data(
            mode="universes",
            target_date="2026-04-28",
            universes=["csi300"],
        )

    assert inference_result == conflict_payload
    assert qlib_result == conflict_payload
