from unittest.mock import Mock, patch

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import ConflictError


def test_get_factor_exposure_uses_alpha_service_provider() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    provider = Mock()
    provider.get_factor_exposure.return_value = {"roe": 0.12}
    service = Mock()
    service._registry.get_provider.return_value = provider

    with patch("agomtradepro.modules.alpha._get_alpha_service", return_value=service):
        result = client.alpha.get_factor_exposure("000001.SH", "2026-02-05", "simple")

    assert result == {
        "success": True,
        "stock_code": "000001.SH",
        "trade_date": "2026-02-05",
        "provider": "simple",
        "factors": {"roe": 0.12},
    }


def test_get_factor_exposure_returns_error_for_unknown_provider() -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    service = Mock()
    service._registry.get_provider.return_value = None

    with patch("agomtradepro.modules.alpha._get_alpha_service", return_value=service):
        result = client.alpha.get_factor_exposure("000001.SH", provider="missing")

    assert result["success"] is False
    assert result["stock_code"] == "000001.SH"
    assert result["factors"] == {}


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
