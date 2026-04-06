from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


@pytest.fixture
def client():
    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


@pytest.mark.parametrize(
    "callable_factory,method,endpoint,expected,result_payload",
    [
        (
            lambda c: c.data_center.list_providers(),
            "GET",
            "/api/data-center/providers/",
            {"params": None},
            [],
        ),
        (
            lambda c: c.data_center.get_provider(7),
            "GET",
            "/api/data-center/providers/7/",
            {"params": None},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.create_provider({"name": "tushare-main"}),
            "POST",
            "/api/data-center/providers/",
            {"data": None, "json": {"name": "tushare-main"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.update_provider(7, {"priority": 2}),
            "PATCH",
            "/api/data-center/providers/7/",
            {"data": None, "json": {"priority": 2}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.delete_provider(7),
            "DELETE",
            "/api/data-center/providers/7/",
            {"params": None},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.test_provider_connection(7),
            "POST",
            "/api/data-center/providers/7/test/",
            {"data": None, "json": {}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_provider_status(),
            "GET",
            "/api/data-center/providers/status/",
            {"params": None},
            [],
        ),
        (
            lambda c: c.data_center.get_macro_series(
                "CN_PMI", start="2026-01-01", end="2026-03-31", limit=12
            ),
            "GET",
            "/api/data-center/macro/series/",
            {
                "params": {
                    "indicator_code": "CN_PMI",
                    "start": "2026-01-01",
                    "end": "2026-03-31",
                    "limit": 12,
                }
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_price_history("000001.SZ", limit=5),
            "GET",
            "/api/data-center/prices/history/",
            {"params": {"asset_code": "000001.SZ", "limit": 5}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_latest_quotes("000001.SZ"),
            "GET",
            "/api/data-center/prices/quotes/",
            {"params": {"asset_code": "000001.SZ"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_capital_flows("000001.SZ", period="10d"),
            "GET",
            "/api/data-center/capital-flows/",
            {"params": {"asset_code": "000001.SZ", "period": "10d"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.sync_capital_flows(
                {"provider_id": 3, "asset_code": "000001.SZ", "period": "5d"}
            ),
            "POST",
            "/api/data-center/sync/capital-flows/",
            {"data": None, "json": {"provider_id": 3, "asset_code": "000001.SZ", "period": "5d"}},
            {"ok": True},
        ),
    ],
)
def test_data_center_module_endpoints(
    client, callable_factory, method, endpoint, expected, result_payload
):
    http_method = method.lower()
    with patch.object(client, http_method, return_value=result_payload) as mocked:
        result = callable_factory(client)
    assert result == result_payload
    mocked.assert_called_once_with(endpoint, **expected)
