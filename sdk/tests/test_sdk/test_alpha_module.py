from unittest.mock import Mock, patch

from agomtradepro import AgomTradeProClient


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
