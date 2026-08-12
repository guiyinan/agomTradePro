"""Governed broker_execution capability and core-only execution evidence."""

import json
from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

BROKER_EXECUTION_KEYS = {
    "broker_execution.read.overview",
    "broker_execution.read.order_catalog",
    "broker_execution.read.order_detail",
    "broker_execution.read.connection_status",
    "broker_execution.read.reconciliation_catalog",
    "broker_execution.read.audit_catalog",
    "broker_execution.approve.order",
    "broker_execution.reject.order",
    "broker_execution.request.cancel",
    "broker_execution.trigger.kill_switch",
    "broker_execution.resume.trading",
    "broker_execution.resolve.reconciliation",
}


def test_broker_execution_manifests_are_governed() -> None:
    registry = CapabilityRegistryLoader().build_registry()
    assert BROKER_EXECUTION_KEYS <= set(registry)
    for key in BROKER_EXECUTION_KEYS:
        manifest = registry[key]
        assert manifest.owner_app == "broker_execution"
        assert manifest.executor_kind == "internal_handler"
        if ".read." in key:
            assert manifest.risk_level == "low"
        else:
            assert manifest.risk_level == "high"
            assert manifest.requires_confirmation is True
            assert manifest.idempotency == "required"
            assert "mcp:write" in manifest.audit_tags
    assert registry["broker_execution.approve.order"].enabled is False
    resume_schema = registry["broker_execution.resume.trading"].input_schema
    assert "reauth_password" in resume_schema["required"]
    assert resume_schema["properties"]["reauth_password"]["writeOnly"] is True


def test_broker_execution_resume_handler_keeps_password_out_of_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agomtradepro_mcp.registry.runtime_handlers.owners import broker_execution

    calls: list[dict] = []

    class _BrokerExecution:
        @staticmethod
        def set_kill_switch(**kwargs):
            calls.append(kwargs)
            return {"preview_only": kwargs["preview_only"]}

    monkeypatch.setattr(
        broker_execution,
        "_client",
        lambda: SimpleNamespace(broker_execution=_BrokerExecution()),
    )
    broker_execution._internal_handler_broker_execution_resume(
        account_id=7,
        reason="review",
        reauth_password="sensitive",
        preview_only=True,
    )
    broker_execution._internal_handler_broker_execution_resume(
        account_id=7,
        reason="review",
        reauth_password="sensitive",
        preview_only=False,
        idempotency_key="resume-7",
    )

    assert calls[0]["reauth_password"] is None
    assert calls[1]["reauth_password"] == "sensitive"


def test_broker_execution_resume_core_confirmation_does_not_echo_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module
    from agomtradepro_mcp.registry.runtime_handlers.owners import broker_execution

    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", "admin")
    calls: list[dict] = []

    class _BrokerExecution:
        @staticmethod
        def set_kill_switch(**kwargs):
            calls.append(kwargs)
            return {"preview_only": kwargs["preview_only"]}

    monkeypatch.setattr(
        broker_execution,
        "_client",
        lambda: SimpleNamespace(broker_execution=_BrokerExecution()),
    )
    staged = server_module.CORE_DISPATCHER.call(
        capability_key="broker_execution.resume.trading",
        arguments={
            "account_id": 7,
            "reason": "readiness restored",
            "reauth_password": "never-echo-this",
            "idempotency_key": "resume-core-password-test",
        },
    )
    resumed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=staged["confirmation_token"],
        approve=True,
    )

    assert staged["status"] == "confirmation_required"
    assert resumed["status"] == "completed"
    assert calls[0]["reauth_password"] is None
    assert calls[1]["reauth_password"] == "never-echo-this"
    assert "never-echo-this" not in json.dumps(staged)
    assert "never-echo-this" not in json.dumps(resumed)


def test_agom_capability_call_reads_broker_execution_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover all native strict reads through INTERNAL_GOVERNED_HANDLERS."""

    import agomtradepro_mcp.server as server_module

    class _BrokerExecution:
        @staticmethod
        def overview():
            return {"today_readiness": "READY"}

        @staticmethod
        def list_orders(**kwargs):
            return {
                "orders": [{"client_order_id": "00000000-0000-0000-0000-000000000001"}],
                "total_count": 1,
            }

        @staticmethod
        def get_order(client_order_id):
            return {"client_order_id": client_order_id, "status": "READY"}

        @staticmethod
        def connections():
            return {"connections": [], "total_count": 0}

        @staticmethod
        def reconciliations(limit=100):
            return {"runs": [], "total_count": 0, "limit": limit}

        @staticmethod
        def audit(limit=100):
            return {"events": [], "total_count": 0, "limit": limit}

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(broker_execution=_BrokerExecution()),
    )
    assert "get_broker_execution_overview" in server_module.INTERNAL_GOVERNED_HANDLERS
    agom_capability_call = server_module.CORE_DISPATCHER.call
    results = [
        agom_capability_call(capability_key="broker_execution.read.overview", arguments={}),
        agom_capability_call(capability_key="broker_execution.read.order_catalog", arguments={}),
        agom_capability_call(
            capability_key="broker_execution.read.order_detail",
            arguments={"client_order_id": "00000000-0000-0000-0000-000000000001"},
        ),
        agom_capability_call(
            capability_key="broker_execution.read.connection_status", arguments={}
        ),
        agom_capability_call(
            capability_key="broker_execution.read.reconciliation_catalog", arguments={}
        ),
        agom_capability_call(capability_key="broker_execution.read.audit_catalog", arguments={}),
    ]
    assert all(item["status"] == "completed" for item in results)


def test_broker_execution_approve_is_disabled_while_risk_reducing_writes_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher

    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", "owner")

    calls: list[dict] = []

    class _BrokerExecution:
        @staticmethod
        def order_action(client_order_id, action, **kwargs):
            calls.append({"client_order_id": client_order_id, "action": action, **kwargs})
            return {"preview_only": kwargs["preview_only"], "action": action}

    registry = CapabilityRegistryLoader().build_registry()
    dispatcher = CapabilityDispatcher(
        registry=registry,
        legacy_tool_caller=lambda _name, _arguments: {},
        internal_handler_caller=lambda _name, _arguments: {},
        role_provider=lambda: "owner",
    )
    assert {
        "broker_execution.approve.order",
        "broker_execution.reject.order",
        "broker_execution.request.cancel",
        "broker_execution.trigger.kill_switch",
        "broker_execution.resume.trading",
        "broker_execution.resolve.reconciliation",
    } <= BROKER_EXECUTION_KEYS
    blocked = dispatcher.call(
        capability_key="broker_execution.approve.order",
        arguments={
            "client_order_id": "00000000-0000-0000-0000-000000000001",
            "reason": "reviewed",
            "expected_version": 3,
            "idempotency_key": "approve-1",
        },
    )
    assert blocked["status"] == "error"
    assert blocked["error"]["code"] == "capability_not_found"
    assert calls == []
    assert dispatcher.get_schema("broker_execution.reject.order")
    assert dispatcher.get_schema("broker_execution.request.cancel")
    assert dispatcher.get_schema("broker_execution.trigger.kill_switch")
