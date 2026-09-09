"""Tushare wire formats respect live egress rules across all supported modes."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.data_center.application import egress_service
from apps.data_center.domain.egress_routing import EgressRouteDecision, EgressStrategy
from apps.data_center.infrastructure import tushare_client


@pytest.mark.parametrize("mode", ["sdk_path", "rest_path", "unified_relay"])
def test_configured_provider_routes_real_query_with_original_wire_format(monkeypatch, mode):
    settings = tushare_client.TushareRuntimeSettings(
        token="test-private-token", http_url="https://market.example.com/pro", request_mode=mode
    )
    monkeypatch.setattr(
        tushare_client, "resolve_tushare_runtime_settings", lambda **_kwargs: settings
    )
    sdk = Mock()
    sdk._DataApi__http_url = settings.http_url
    sdk_module = SimpleNamespace(pro_api=lambda _token: sdk)
    original_import = tushare_client.import_module
    monkeypatch.setattr(
        tushare_client,
        "import_module",
        lambda name: sdk_module if name == "tushare" else original_import(name),
    )
    session = Mock()
    session.headers = {}
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    route = EgressRouteDecision(
        rule_id=5, strategy=EgressStrategy.FIXED, candidates=(9,), reason="matched_rule"
    )
    preview = Mock(return_value=route)
    monkeypatch.setattr(egress_service, "preview_route", preview)
    execute = Mock(
        return_value={
            "code": 0,
            "data": {"fields": ["ts_code", "close"], "items": [["000001.SZ", 12.3]]},
        }
    )
    monkeypatch.setattr(egress_service, "execute_provider_request", execute)
    before = dict(os.environ)
    client = tushare_client.create_tushare_pro_client(
        provider_id=3, deployment_region="overseas", dataset_key="equity.price.bar"
    )
    result = client.daily(ts_code="000001.SZ")
    assert result.iloc[0]["close"] == 12.3
    context = execute.call_args.args[0]
    assert context.provider_id == 3
    assert context.dataset_key == "equity.price.bar"
    expected_suffix = "" if mode == "unified_relay" else "/daily"
    assert context.target_url == settings.http_url + expected_suffix
    assert execute.call_args.kwargs["method"] == ("GET" if mode == "rest_path" else "POST")
    assert execute.call_args.kwargs["max_attempts"] == 2
    assert dict(os.environ) == before
    sdk.query.assert_not_called()
    session.get.assert_not_called()
    session.post.assert_not_called()


def test_sdk_rechecks_rule_when_existing_client_is_reused(monkeypatch):
    sdk = Mock()
    sdk.query.return_value = "legacy-result"
    client = tushare_client._RoutedSdkClient(
        sdk_client=sdk,
        token="test-token",
        http_url="https://market.example.com/pro",
        provider_id=3,
        deployment_region="overseas",
        dataset_key="",
    )
    direct = EgressRouteDecision(
        rule_id=None, strategy=EgressStrategy.DIRECT, candidates=(None,), reason="no_matching_rule"
    )
    fixed = EgressRouteDecision(
        rule_id=5, strategy=EgressStrategy.FIXED, candidates=(9,), reason="matched_rule"
    )
    monkeypatch.setattr(egress_service, "preview_route", Mock(side_effect=[direct, fixed]))
    execute = Mock(return_value={"code": 0, "data": {"fields": ["name"], "items": [["example"]]}})
    monkeypatch.setattr(egress_service, "execute_provider_request", execute)
    assert client.stock_basic() == "legacy-result"
    assert client.stock_basic().iloc[0]["name"] == "example"
    assert sdk.query.call_count == 1
    assert execute.call_args.args[0].dataset_key == "tushare.stock_basic"
