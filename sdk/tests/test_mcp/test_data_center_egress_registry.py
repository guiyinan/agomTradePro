"""Core-only discovery, authorization and confirmed egress configuration workflows."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro_mcp.audit import AuditLogger
from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.modules.owners.data_center_egress_capabilities import MANIFESTS
from agomtradepro_mcp.registry.runtime_handlers.owners.data_center_egress import GOVERNED_HANDLERS

CONTEXT = {
    "provider_id": 3,
    "dataset_key": "equity.price.bar",
    "deployment_region": "overseas",
    "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
}
ENDPOINT = {
    "name": "Mainland",
    "region": "cn",
    "protocol": "http",
    "host": "frpc_egress_visitor",
    "port": 18080,
}
RULE = {
    "provider_id": 3,
    "dataset_key": "equity.price.bar",
    "domain_pattern": "push2his.eastmoney.com",
    "deployment_region": "overseas",
    "strategy": "fixed",
    "fixed_egress_id": 7,
    "priority": 10,
}


@pytest.fixture
def harness(monkeypatch):
    import agomtradepro

    module = Mock()
    module.get_egress_endpoint.return_value = {
        "id": 7,
        **ENDPOINT,
        "enabled": False,
        "password": "must-not-escape",
    }
    module.get_egress_rule.return_value = {"id": 8, **RULE, "enabled": False}
    module.list_egress_endpoints.return_value = [module.get_egress_endpoint.return_value]
    module.list_egress_rules.return_value = [module.get_egress_rule.return_value]
    module.preview_egress_route.return_value = {"rule_id": 8, "strategy": "fixed", "egress_id": 7}
    for method in (
        "create_egress_endpoint",
        "update_egress_endpoint",
        "create_egress_rule",
        "update_egress_rule",
    ):
        getattr(module, method).return_value = {"id": 7, "enabled": False}
    for method in ("test_egress_endpoint", "diagnose_egress_route"):
        getattr(module, method).return_value = {
            "outcome": "blocked",
            "error_code": "EGRESS_TARGET_NOT_ALLOWED",
            "message": "Target blocked",
            "attempts": [],
            "password": "must-not-escape",
        }
    monkeypatch.setattr(
        agomtradepro, "AgomTradeProClient", lambda: SimpleNamespace(data_center=module)
    )
    events = []
    dispatcher = CapabilityDispatcher(
        registry=CapabilityRegistryLoader().build_registry(),
        legacy_tool_caller=Mock(side_effect=AssertionError("Legacy tools must not be called")),
        internal_handler_caller=lambda ref, args: GOVERNED_HANDLERS[ref](**args),
        role_provider=lambda: "staff",
        audit_logger=SimpleNamespace(
            log_governed_capability_event=lambda **kw: events.append(
                AuditLogger._mask_sensitive_params(kw)
            )
            or "test"
        ),
    )
    return dispatcher, module, events


@pytest.mark.parametrize(
    ("key", "arguments", "method"),
    [
        ("data_center.read.egress_endpoints", {}, "list_egress_endpoints"),
        ("data_center.read.egress_endpoint", {"endpoint_id": 7}, "get_egress_endpoint"),
        ("data_center.read.egress_rules", {}, "list_egress_rules"),
        ("data_center.read.egress_rule", {"rule_id": 8}, "get_egress_rule"),
        ("data_center.read.egress_route_preview", CONTEXT, "preview_egress_route"),
    ],
)
def test_agom_capability_call_reads_egress_in_core_only_mode(
    monkeypatch, core_only_mcp_server, harness, key, arguments, method
):
    import agomtradepro_mcp.server as server_module

    dispatcher, module, _ = harness
    assert key.replace(".", "_") in server_module.INTERNAL_GOVERNED_HANDLERS
    monkeypatch.setattr(server_module.CORE_DISPATCHER, "_role_provider", lambda: "staff")
    monkeypatch.setattr(server_module.CORE_DISPATCHER, "_audit_logger", dispatcher._audit_logger)
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call", {"capability_key": key, "arguments": arguments}
        )
    )
    assert "completed" in str(result)
    assert "must-not-escape" not in str(result)
    getattr(module, method).assert_called_once()


@pytest.mark.parametrize(
    ("key", "arguments", "method"),
    [
        ("data_center.create.egress_endpoint", ENDPOINT, "create_egress_endpoint"),
        (
            "data_center.update.egress_endpoint",
            {"endpoint_id": 7, "enabled": False},
            "update_egress_endpoint",
        ),
        ("data_center.create.egress_rule", RULE, "create_egress_rule"),
        (
            "data_center.update.egress_rule",
            {"rule_id": 8, "enabled": False, "fixed_egress_id": None, "strategy": "direct"},
            "update_egress_rule",
        ),
        (
            "data_center.run.egress_endpoint_test",
            {"endpoint_id": 7, **CONTEXT},
            "test_egress_endpoint",
        ),
        ("data_center.run.egress_diagnostics", CONTEXT, "diagnose_egress_route"),
    ],
)
def test_writes_and_probes_preview_confirm_audit_and_replay_once(harness, key, arguments, method):
    dispatcher, module, events = harness
    args = {**arguments, "idempotency_key": "test-operation"}
    preview = dispatcher.call(capability_key=key, arguments=args)
    assert preview["status"] == "confirmation_required"
    assert preview["preview_result"]["preview_only"] is True
    getattr(module, method).assert_not_called()
    assert (
        dispatcher.call(capability_key=key, arguments=args)["confirmation_token"]
        == preview["confirmation_token"]
    )
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["status"] == "completed"
    getattr(module, method).assert_called_once()
    assert "idempotency_key" not in str(getattr(module, method).call_args)
    if ".run." in key:
        assert result["result"]["outcome"] == "blocked"
        assert result["result"]["error_code"] == "EGRESS_TARGET_NOT_ALLOWED"
    if method == "update_egress_rule":
        module.update_egress_rule.assert_called_once_with(
            8, {"enabled": False, "fixed_egress_id": None, "strategy": "direct"}
        )
    assert dispatcher.call(capability_key=key, arguments=args)["status"] == "idempotent_replay"
    getattr(module, method).assert_called_once()
    assert any(event["event_type"] == "confirmation_completed" for event in events)


def test_credentials_are_write_only_and_backend_errors_are_sanitized(harness):
    dispatcher, module, events = harness
    args = {
        **ENDPOINT,
        "credential_username": "private-user",
        "credential_password": "private-secret",
        "idempotency_key": "credentials",
    }
    preview = dispatcher.call(capability_key="data_center.create.egress_endpoint", arguments=args)
    assert "private-" not in json.dumps(preview)
    module.create_egress_endpoint.side_effect = AgomTradeProAPIError(
        "private-user:private-secret", status_code=400
    )
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert "private-" not in json.dumps(result)
    assert "private-" not in json.dumps(events, default=str)
    payload = module.create_egress_endpoint.call_args.args[0]
    assert payload["username"] == "private-user"
    assert payload["password"] == "private-secret"
    assert "credential_password" not in payload


@pytest.mark.parametrize(
    "arguments",
    [
        {"endpoint_id": True, "enabled": False},
        {"endpoint_id": 7, "enabled": "false"},
        {"endpoint_id": 7, "port": 65536},
        {"endpoint_id": 7, "enabled": None},
        {"endpoint_id": 7, "unknown_field": "value"},
        {"endpoint_id": 7},
    ],
)
def test_invalid_patch_is_rejected_before_preview_io(harness, arguments):
    dispatcher, module, _ = harness
    response = dispatcher.call(
        capability_key="data_center.update.egress_endpoint",
        arguments={**arguments, "idempotency_key": "invalid"},
    )
    assert response["ok"] is False
    assert response["status"] != "confirmation_required"
    assert module.mock_calls == []


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "https://user:secret@example.com"},
        {"url": "file:///etc/passwd"},
        {"dataset_key": "*"},
        {"deployment_region": "*"},
    ],
)
def test_invalid_probe_context_performs_no_request(harness, patch):
    dispatcher, module, events = harness
    result = dispatcher.call(
        capability_key="data_center.run.egress_diagnostics",
        arguments={**CONTEXT, **patch, "idempotency_key": "invalid"},
    )
    assert result["ok"] is False
    assert result["status"] != "confirmation_required"
    assert module.mock_calls == []
    assert "user:secret" not in json.dumps(events, default=str)


def test_target_query_is_sent_intact_but_redacted_from_preview_and_audit(harness):
    dispatcher, module, events = harness
    target = CONTEXT["url"] + "?token=private-query-value"
    preview = dispatcher.call(
        capability_key="data_center.run.egress_diagnostics",
        arguments={**CONTEXT, "url": target, "idempotency_key": "target-query"},
    )
    assert preview["status"] == "confirmation_required"
    assert "private-query-value" not in json.dumps(preview)
    module.preview_egress_route.assert_called_once_with({**CONTEXT, "url": target})
    dispatcher.resume_confirmation(confirmation_token=preview["confirmation_token"], approve=True)
    module.diagnose_egress_route.assert_called_once_with({**CONTEXT, "url": target})
    assert "private-query-value" not in json.dumps(events, default=str)


def test_all_egress_capabilities_require_staff_and_are_discoverable(harness):
    dispatcher, module, _ = harness
    assert len(dispatcher.search(query="frpc", limit=20)) == 11
    dispatcher._role_provider = lambda: "viewer"
    assert dispatcher.search(query="frpc", limit=20) == []
    for manifest in MANIFESTS:
        result = dispatcher.call(capability_key=manifest.capability_key, arguments={})
        assert result["ok"] is False
    assert module.mock_calls == []


def test_staff_owner_can_discover_and_preview_without_granting_nonstaff_owner(harness, monkeypatch):
    from agomtradepro_mcp import rbac

    dispatcher, module, _ = harness
    dispatcher._role_provider = lambda: "owner"
    monkeypatch.setattr(rbac, "_BACKEND_PROFILE_CACHE", {"rbac_role": "owner", "is_staff": True})
    assert len(dispatcher.search(query="frpc", limit=20)) == 11
    result = dispatcher.call(
        capability_key="data_center.create.egress_endpoint",
        arguments={**ENDPOINT, "idempotency_key": "staff-owner"},
    )
    assert result["status"] == "confirmation_required"
    monkeypatch.setattr(rbac, "_BACKEND_PROFILE_CACHE", {"rbac_role": "owner", "is_staff": False})
    assert dispatcher.search(query="frpc", limit=20) == []
    result = dispatcher.resume_confirmation(
        confirmation_token=result["confirmation_token"], approve=True
    )
    assert result["ok"] is False
    module.create_egress_endpoint.assert_not_called()


def test_cancel_and_role_revocation_prevent_configuration_write(harness):
    dispatcher, module, _ = harness
    key = "data_center.create.egress_endpoint"
    preview = dispatcher.call(
        capability_key=key, arguments={**ENDPOINT, "idempotency_key": "cancel"}
    )
    dispatcher.resume_confirmation(confirmation_token=preview["confirmation_token"], approve=False)
    module.create_egress_endpoint.assert_not_called()
    preview = dispatcher.call(
        capability_key=key, arguments={**ENDPOINT, "idempotency_key": "revoked"}
    )
    dispatcher._role_provider = lambda: "viewer"
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["ok"] is False
    module.create_egress_endpoint.assert_not_called()


def test_missing_idempotency_key_is_rejected(harness):
    dispatcher, module, _ = harness
    response = dispatcher.call(
        capability_key="data_center.create.egress_endpoint", arguments=ENDPOINT
    )
    assert response["ok"] is False
    assert module.mock_calls == []
