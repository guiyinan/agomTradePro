"""Exercise MCP confirmation through the real SDK and persisted Django egress API."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from agomtradepro import AgomTradeProClient
from agomtradepro.transport import use_request_transport
from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.runtime_handlers.owners.data_center_egress import GOVERNED_HANDLERS
from apps.config_center.application.public import get_egress_endpoint
from apps.data_center.application import egress_service
from apps.data_center.infrastructure.models import ProviderConfigModel


class DjangoTransport:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def request(self, *, method, url, **kwargs):
        path = urlsplit(url).path
        self.calls.append((method, path))
        if method == "GET":
            response = self.client.get(path, data=kwargs.get("params") or {})
        else:
            response = self.client.generic(
                method,
                path,
                data=json.dumps(kwargs.get("json") or {}),
                content_type="application/json",
            )
        assert response["Content-Type"].startswith("application/json"), response.content
        return response


@pytest.fixture
def workflow(db, monkeypatch):
    import agomtradepro

    operator = get_user_model().objects.create_user(username="mcp-egress", is_staff=True)
    http = Client()
    http.force_login(operator)
    sdk = AgomTradeProClient(base_url="http://testserver", api_token="test-only")
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: sdk)
    dispatcher = CapabilityDispatcher(
        registry=CapabilityRegistryLoader().build_registry(),
        legacy_tool_caller=Mock(side_effect=AssertionError("Legacy access is disabled")),
        internal_handler_caller=lambda ref, args: GOVERNED_HANDLERS[ref](**args),
        role_provider=lambda: "staff",
        audit_logger=SimpleNamespace(log_governed_capability_event=lambda **kw: "local-test"),
    )
    provider = ProviderConfigModel.objects.create(name="mcp-egress-market", source_type="akshare")
    transport = DjangoTransport(http)
    with use_request_transport(transport):
        yield dispatcher, transport, provider.pk, operator
    sdk.close()


def confirmed(dispatcher, key, arguments, operation):
    args = {**arguments, "idempotency_key": operation}
    preview = dispatcher.call(capability_key=key, arguments=args)
    assert preview["status"] == "confirmation_required", preview
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["status"] == "completed", result
    return result["result"]


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="mcp-egress-local-test-encryption")
def test_mcp_register_test_enable_route_disable_and_clear_credentials(workflow, monkeypatch):
    dispatcher, http, provider_id, _ = workflow
    args = {
        "name": "MCP mainland",
        "region": "cn",
        "protocol": "http",
        "host": "frpc_egress_visitor",
        "port": 18080,
        "credential_username": "test-proxy-user",
        "credential_password": "test-proxy-password",
    }
    preview = dispatcher.call(
        capability_key="data_center.create.egress_endpoint",
        arguments={**args, "idempotency_key": "register"},
    )
    assert preview["status"] == "confirmation_required"
    assert http.calls == []
    endpoint = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )["result"]
    endpoint_id = endpoint["id"]
    assert endpoint["enabled"] is False
    assert endpoint["password_configured"] is True
    assert "test-proxy-password" not in str(endpoint)
    assert get_egress_endpoint(endpoint_id).password == "test-proxy-password"
    rule = confirmed(
        dispatcher,
        "data_center.create.egress_rule",
        {
            "provider_id": provider_id,
            "dataset_key": "equity.price.bar",
            "domain_pattern": "push2his.eastmoney.com",
            "deployment_region": "overseas",
            "strategy": "fixed",
            "fixed_egress_id": endpoint_id,
            "priority": 10,
        },
        "rule",
    )
    rule_id = rule["id"]
    assert rule["enabled"] is False
    context = {
        "provider_id": provider_id,
        "dataset_key": "equity.price.bar",
        "deployment_region": "overseas",
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    }
    network = Mock()
    network.probe_endpoint.return_value = egress_service.EgressTransportResult(
        outcome="success", status_code=200
    )
    network.request.return_value = egress_service.EgressTransportResult(
        outcome="failed",
        error_code="EGRESS_CONNECT_FAILED",
        message="Connection failed",
        retryable=False,
    )
    monkeypatch.setattr(egress_service, "_transport", network)
    probe_preview = dispatcher.call(
        capability_key="data_center.run.egress_endpoint_test",
        arguments={"endpoint_id": endpoint_id, **context, "idempotency_key": "probe"},
    )
    network.probe_endpoint.assert_not_called()
    result = dispatcher.resume_confirmation(
        confirmation_token=probe_preview["confirmation_token"], approve=True
    )
    assert result["result"]["outcome"] == "success", result
    network.probe_endpoint.assert_called_once()
    assert network.probe_endpoint.call_args.kwargs["egress_id"] == endpoint_id
    confirmed(
        dispatcher,
        "data_center.update.egress_endpoint",
        {"endpoint_id": endpoint_id, "enabled": True, "credential_password": ""},
        "enable-exit",
    )
    assert get_egress_endpoint(endpoint_id).password == "test-proxy-password"
    confirmed(
        dispatcher,
        "data_center.update.egress_rule",
        {"rule_id": rule_id, "enabled": True},
        "enable-rule",
    )
    preview = dispatcher.call(
        capability_key="data_center.read.egress_route_preview", arguments=context
    )
    assert preview["result"]["egress_id"] == endpoint_id
    network.request.assert_not_called()
    diagnosis = confirmed(dispatcher, "data_center.run.egress_diagnostics", context, "diagnose")
    assert diagnosis["outcome"] == "failed"
    assert diagnosis["attempts"][0]["error_code"] == "EGRESS_CONNECT_FAILED"
    network.request.assert_called_once()
    listed = dispatcher.call(capability_key="data_center.read.egress_rules", arguments={})
    assert listed["result"]["results"][0]["id"] == rule_id
    confirmed(
        dispatcher,
        "data_center.update.egress_rule",
        {"rule_id": rule_id, "enabled": False, "strategy": "direct", "fixed_egress_id": None},
        "disable-rule",
    )
    updated = confirmed(
        dispatcher,
        "data_center.update.egress_endpoint",
        {"endpoint_id": endpoint_id, "enabled": False, "clear_credentials": True},
        "disable-exit",
    )
    assert updated["enabled"] is False
    assert updated["username_configured"] is False
    assert updated["password_configured"] is False


@pytest.mark.django_db
def test_backend_permission_still_denies_when_mcp_role_is_staff(workflow):
    dispatcher, _, _, operator = workflow
    operator.is_staff = False
    operator.save(update_fields=["is_staff"])
    result = dispatcher.call(capability_key="data_center.read.egress_endpoints", arguments={})
    assert result["ok"] is False
    assert result["status"] != "completed"
