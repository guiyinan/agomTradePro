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
            lambda c: c.data_center.get_publisher("NBS"),
            "GET",
            "/api/data-center/publishers/NBS/",
            {"params": None},
            {"code": "NBS"},
        ),
        (
            lambda c: c.data_center.list_publishers(active_only=True),
            "GET",
            "/api/data-center/publishers/",
            {"params": {"active_only": "true"}},
            [],
        ),
        (
            lambda c: c.data_center.list_indicators(active_only=True),
            "GET",
            "/api/data-center/indicators/",
            {"params": {"active_only": "true"}},
            [],
        ),
        (
            lambda c: c.data_center.get_indicator("CN_PMI"),
            "GET",
            "/api/data-center/indicators/CN_PMI/",
            {"params": None},
            {"code": "CN_PMI"},
        ),
        (
            lambda c: c.data_center.create_indicator({"code": "CN_PMI", "name_cn": "制造业PMI"}),
            "POST",
            "/api/data-center/indicators/",
            {"data": None, "json": {"code": "CN_PMI", "name_cn": "制造业PMI"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.update_indicator("CN_PMI", {"category": "growth"}),
            "PATCH",
            "/api/data-center/indicators/CN_PMI/",
            {"data": None, "json": {"category": "growth"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.delete_indicator("CN_PMI"),
            "DELETE",
            "/api/data-center/indicators/CN_PMI/",
            {"params": None},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.list_indicator_unit_rules("CN_PMI"),
            "GET",
            "/api/data-center/indicators/CN_PMI/unit-rules/",
            {"params": None},
            [],
        ),
        (
            lambda c: c.data_center.get_indicator_unit_rule("CN_PMI", 7),
            "GET",
            "/api/data-center/indicators/CN_PMI/unit-rules/7/",
            {"params": None},
            {"id": 7},
        ),
        (
            lambda c: c.data_center.create_indicator_unit_rule(
                "CN_PMI",
                {"dimension_key": "index_level", "storage_unit": "指数"},
            ),
            "POST",
            "/api/data-center/indicators/CN_PMI/unit-rules/",
            {"data": None, "json": {"dimension_key": "index_level", "storage_unit": "指数"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.update_indicator_unit_rule("CN_PMI", 7, {"priority": 10}),
            "PATCH",
            "/api/data-center/indicators/CN_PMI/unit-rules/7/",
            {"data": None, "json": {"priority": 10}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.delete_indicator_unit_rule("CN_PMI", 7),
            "DELETE",
            "/api/data-center/indicators/CN_PMI/unit-rules/7/",
            {"params": None},
            {"ok": True},
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
                    "mode": "published",
                }
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.sync_macro(
                {
                    "provider_id": 3,
                    "indicator_code": "CN_PMI",
                    "start": "2026-01-01",
                    "end": "2026-03-31",
                }
            ),
            "POST",
            "/api/data-center/sync/macro/",
            {
                "data": None,
                "json": {
                    "provider_id": 3,
                    "indicator_code": "CN_PMI",
                    "start": "2026-01-01",
                    "end": "2026-03-31",
                },
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_price_history(
                "000001.SZ",
                start="2026-04-01",
                end="2026-04-21",
                freq="1d",
                adjustment="qfq",
                limit=5,
            ),
            "GET",
            "/api/data-center/prices/history/",
            {
                "params": {
                    "asset_code": "000001.SZ",
                    "start": "2026-04-01",
                    "end": "2026-04-21",
                    "freq": "1d",
                    "adjustment": "qfq",
                    "limit": 5,
                    "mode": "published",
                }
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_latest_quotes("000001.SZ"),
            "GET",
            "/api/data-center/prices/quotes/",
            {"params": {"asset_code": "000001.SZ", "mode": "published"}},
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_latest_quotes(
                "000001.SZ",
                strict_freshness=True,
                max_age_hours=1.5,
            ),
            "GET",
            "/api/data-center/prices/quotes/",
            {
                "params": {
                    "asset_code": "000001.SZ",
                    "strict_freshness": "true",
                    "max_age_hours": 1.5,
                    "mode": "published",
                }
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_news("000001.SZ", limit=5),
            "GET",
            "/api/data-center/news/",
            {
                "params": {
                    "asset_code": "000001.SZ",
                    "limit": 5,
                    "mode": "published",
                }
            },
            {"ok": True},
        ),
        (
            lambda c: c.data_center.get_capital_flows(
                "000001.SZ",
                start="2026-04-01",
                end="2026-04-10",
                limit=10,
            ),
            "GET",
            "/api/data-center/capital-flows/",
            {
                "params": {
                    "asset_code": "000001.SZ",
                    "start": "2026-04-01",
                    "end": "2026-04-10",
                    "limit": 10,
                    "mode": "published",
                }
            },
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
        (
            lambda c: c.data_center.repair_decision_data_reliability(
                target_date="2026-04-21",
                portfolio_id=366,
                asset_codes=["510300.SH"],
                strict=True,
            ),
            "POST",
            "/api/data-center/decision-reliability/repair/",
            {
                "data": None,
                "json": {
                    "strict": True,
                    "target_date": "2026-04-21",
                    "portfolio_id": 366,
                    "asset_codes": ["510300.SH"],
                },
            },
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


def test_data_center_module_can_request_publication_gated_reads(client):
    with patch.object(client, "get", return_value={"status": "blocked"}) as mocked:
        result = client.data_center.get_price_history(
            "002156.SZ",
            limit=10,
            mode="published",
            publication_key="current",
        )

    assert result == {"status": "blocked"}
    mocked.assert_called_once_with(
        "/api/data-center/prices/history/",
        params={
            "asset_code": "002156.SZ",
            "limit": 10,
            "mode": "published",
            "publication_key": "current",
        },
    )


def test_data_center_module_propagates_publication_gate_for_news_and_sectors(client):
    """D7 SDK reads must not silently drop mode/publication parameters."""

    with patch.object(client, "get", return_value={"status": "blocked"}) as mocked:
        news_result = client.data_center.get_news(
            "002156.SZ",
            limit=10,
            mode="published",
            publication_key="current",
        )
    assert news_result == {"status": "blocked"}
    mocked.assert_called_once_with(
        "/api/data-center/news/",
        params={
            "asset_code": "002156.SZ",
            "limit": 10,
            "mode": "published",
            "publication_key": "current",
        },
    )

    with patch.object(client, "get", return_value={"status": "blocked"}) as mocked:
        sector_result = client.data_center.get_sector_constituents(
            "801010",
            mode="published",
            publication_key="current",
        )
    assert sector_result == {"status": "blocked"}
    mocked.assert_called_once_with(
        "/api/data-center/sectors/constituents/",
        params={
            "sector_code": "801010",
            "mode": "published",
            "publication_key": "current",
        },
    )


def _egress_context() -> dict[str, object]:
    """Return a concrete request context accepted by the egress API."""

    return {
        "provider_id": 3,
        "dataset_key": "equity.price.bar",
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "deployment_region": "overseas",
    }


@pytest.mark.parametrize(
    "callable_factory,method,endpoint,expected,result_payload",
    [
        (
            lambda c: c.data_center.list_egress_endpoints(),
            "GET",
            "/api/data-center/egress/endpoints/",
            {"params": None},
            {"results": [{"id": 7, "name": "CN exit"}]},
        ),
        (
            lambda c: c.data_center.get_egress_endpoint(7),
            "GET",
            "/api/data-center/egress/endpoints/7/",
            {"params": None},
            {"id": 7, "password_configured": True},
        ),
        (
            lambda c: c.data_center.create_egress_endpoint(
                {"name": "CN exit", "region": "cn", "protocol": "http"}
            ),
            "POST",
            "/api/data-center/egress/endpoints/",
            {
                "data": None,
                "json": {"name": "CN exit", "region": "cn", "protocol": "http"},
            },
            {"id": 7},
        ),
        (
            lambda c: c.data_center.update_egress_endpoint(7, {"enabled": False}),
            "PATCH",
            "/api/data-center/egress/endpoints/7/",
            {"data": None, "json": {"enabled": False}},
            {"id": 7, "enabled": False},
        ),
        (
            lambda c: c.data_center.test_egress_endpoint(7, _egress_context()),
            "POST",
            "/api/data-center/egress/endpoints/7/test/",
            {"data": None, "json": _egress_context()},
            {"outcome": "success"},
        ),
        (
            lambda c: c.data_center.list_egress_rules(),
            "GET",
            "/api/data-center/egress/rules/",
            {"params": None},
            {"results": [{"id": 11, "strategy": "fixed"}]},
        ),
        (
            lambda c: c.data_center.get_egress_rule(11),
            "GET",
            "/api/data-center/egress/rules/11/",
            {"params": None},
            {"id": 11, "strategy": "fixed"},
        ),
        (
            lambda c: c.data_center.create_egress_rule(
                {
                    "provider_id": 3,
                    "dataset_key": "equity.price.bar",
                    "domain_pattern": "push2his.eastmoney.com",
                    "deployment_region": "overseas",
                    "strategy": "fixed",
                    "fixed_egress_id": 7,
                    "priority": 10,
                }
            ),
            "POST",
            "/api/data-center/egress/rules/",
            {
                "data": None,
                "json": {
                    "provider_id": 3,
                    "dataset_key": "equity.price.bar",
                    "domain_pattern": "push2his.eastmoney.com",
                    "deployment_region": "overseas",
                    "strategy": "fixed",
                    "fixed_egress_id": 7,
                    "priority": 10,
                },
            },
            {"id": 11},
        ),
        (
            lambda c: c.data_center.update_egress_rule(11, {"enabled": False}),
            "PATCH",
            "/api/data-center/egress/rules/11/",
            {"data": None, "json": {"enabled": False}},
            {"id": 11, "enabled": False},
        ),
        (
            lambda c: c.data_center.preview_egress_route(_egress_context()),
            "POST",
            "/api/data-center/egress/rules/preview/",
            {"data": None, "json": _egress_context()},
            {"outcome": "success", "egress_id": 7},
        ),
        (
            lambda c: c.data_center.diagnose_egress_route(_egress_context()),
            "POST",
            "/api/data-center/egress/diagnostics/",
            {"data": None, "json": _egress_context()},
            {"outcome": "blocked", "error_code": "EGRESS_NO_RULE"},
        ),
    ],
)
def test_data_center_egress_module_endpoints(
    client, callable_factory, method, endpoint, expected, result_payload
):
    """All staff egress SDK methods use the canonical route and HTTP verb."""

    http_method = method.lower()
    with patch.object(client, http_method, return_value=result_payload) as mocked:
        result = callable_factory(client)
    if method == "GET" and endpoint.endswith(("endpoints/", "rules/")):
        assert result == result_payload["results"]
    else:
        assert result == result_payload
    mocked.assert_called_once_with(endpoint, **expected)


def test_data_center_egress_endpoint_credential_aliases_are_translated(client):
    """MCP-safe credential names map to the API write-only field names."""

    payload = {
        "name": "CN exit",
        "region": "cn",
        "protocol": "http",
        "credential_username": "proxy-user",
        "credential_password": "proxy-secret",
    }
    with patch.object(client, "post", return_value={"id": 7}) as mocked:
        result = client.data_center.create_egress_endpoint(payload)

    assert result == {"id": 7}
    mocked.assert_called_once_with(
        "/api/data-center/egress/endpoints/",
        data=None,
        json={
            "name": "CN exit",
            "region": "cn",
            "protocol": "http",
            "username": "proxy-user",
            "password": "proxy-secret",
        },
    )
    assert payload["credential_username"] == "proxy-user"
    assert payload["credential_password"] == "proxy-secret"


def test_data_center_egress_patch_preserves_false_null_and_omitted_fields(client):
    """PATCH payloads retain explicit false/null values and omit untouched keys."""

    with patch.object(client, "patch", return_value={"ok": True}) as mocked:
        client.data_center.update_egress_endpoint(7, {"enabled": False})
        client.data_center.update_egress_endpoint(7, {"clear_credentials": False})
        client.data_center.update_egress_rule(11, {"fixed_egress_id": None})

    assert [call.kwargs["json"] for call in mocked.call_args_list] == [
        {"enabled": False},
        {"clear_credentials": False},
        {"fixed_egress_id": None},
    ]
    assert mocked.call_args_list[0].args == ("/api/data-center/egress/endpoints/7/",)
    assert mocked.call_args_list[2].args == ("/api/data-center/egress/rules/11/",)


def test_data_center_egress_diagnostic_preserves_blocked_business_outcome(client):
    """A HTTP-200 business failure remains visible to SDK callers."""

    blocked = {
        "outcome": "blocked",
        "error_code": "EGRESS_DIAGNOSTIC_RULE_REQUIRED",
        "message": "target is not allowlisted",
    }
    with patch.object(client, "post", return_value=blocked) as mocked:
        result = client.data_center.diagnose_egress_route(_egress_context())

    assert result == blocked
    assert result["outcome"] == "blocked"
    mocked.assert_called_once_with(
        "/api/data-center/egress/diagnostics/",
        data=None,
        json=_egress_context(),
    )


@pytest.mark.parametrize(
    "method_name,arguments",
    [
        ("get_egress_endpoint", (0,)),
        ("update_egress_endpoint", (0, {})),
        ("test_egress_endpoint", (0, {})),
        ("get_egress_rule", (0,)),
        ("update_egress_rule", (0, {})),
    ],
)
def test_data_center_egress_methods_reject_non_positive_ids(client, method_name, arguments):
    """Numeric path identifiers are validated before any HTTP call."""

    with (
        patch.object(client, "get") as get,
        patch.object(client, "patch") as patch_request,
        patch.object(client, "post") as post,
    ):
        with pytest.raises(ValueError, match="positive integer"):
            getattr(client.data_center, method_name)(*arguments)
    get.assert_not_called()
    patch_request.assert_not_called()
    post.assert_not_called()


def test_data_center_egress_context_rejects_embedded_credentials(client):
    """Target URLs cannot smuggle credentials into diagnostics or previews."""

    context = _egress_context()
    context["url"] = "https://private-user:private-secret@example.com/data"
    with patch.object(client, "post") as mocked:
        with pytest.raises(ValueError, match="without credentials"):
            client.data_center.preview_egress_route(context)
    mocked.assert_not_called()
