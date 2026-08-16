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


def _governed_order_detail() -> dict:
    return {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "account_id": 7,
        "agent_id": "agent-7",
        "asset_code": "510300.SH",
        "market": "CN",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100",
        "limit_price": "4.0000",
        "estimated_amount": "400.00",
        "status": "WAITING_APPROVAL",
        "source_recommendation_ids": ["recommendation-1"],
        "source_signal_ids": [],
        "risk_policy_version": "risk-v1",
        "risk_snapshot": {"arbitrary": {"must_not_escape": True}},
        "approval_mode": "manual",
        "approval_digest": "",
        "approved_by": None,
        "approved_at": None,
        "expires_at": "2026-08-13T13:00:00+00:00",
        "submitted_at": None,
        "broker_order_id": "",
        "filled_quantity": "0.0000",
        "average_fill_price": None,
        "failure_code": "",
        "failure_message": "",
        "version": 1,
        "created_at": "2026-08-13T11:00:00+00:00",
        "updated_at": "2026-08-13T11:30:00+00:00",
        "events": [
            {
                "event_id": "event-1",
                "event_type": "ORDER_REVIEWED",
                "status": "WAITING_APPROVAL",
                "occurred_at": "2026-08-13T11:20:00+00:00",
                "received_at": "2026-08-13T11:20:01+00:00",
                "payload": {"must_not_escape": True},
            }
        ],
        "fills": [],
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "lifecycle_transitions": {"approve": True, "reject": True, "cancel": True},
        "actor_authorization": {"approve": False, "reject": True, "cancel": True},
        "transport_blocker_codes": [],
        "event_payload_policy": "omitted_untyped",
        "risk_snapshot_policy": "content_hash_only",
        "risk_snapshot_content_hash": "0" * 64,
        "approval_evidence_status": "blocked",
        "approval_evidence_blocker_codes": ["broker_order_approval_missing"],
        "approval_evidence": None,
        "permission": "display_only",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "unexpected": "must-not-escape",
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
    assert registry["broker_execution.read.order_detail"].enabled is True
    assert all(
        registry[key].enabled is False
        for key in {
            "broker_execution.read.overview",
            "broker_execution.read.order_catalog",
            "broker_execution.read.connection_status",
            "broker_execution.read.reconciliation_catalog",
            "broker_execution.read.audit_catalog",
        }
    )
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


def test_order_detail_is_the_only_enabled_broker_read_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep untyped catalogs disabled while restoring one governed detail."""

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
            assert client_order_id == "00000000-0000-0000-0000-000000000001"
            return _governed_order_detail()

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
    completed = agom_capability_call(
        capability_key="broker_execution.read.order_detail",
        arguments={"client_order_id": "00000000-0000-0000-0000-000000000001"},
    )
    blocked = agom_capability_call(capability_key="broker_execution.read.overview", arguments={})

    assert completed["status"] == "completed"
    assert blocked["status"] == "error"
    assert blocked["error"]["code"] == "capability_not_found"


def test_disabled_broker_catalogs_are_explicitly_gated_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove disabled native catalogs are blocked before their handlers run."""

    import agomtradepro_mcp.server as server_module

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(broker_execution=object()),
    )
    agom_capability_call = server_module.CORE_DISPATCHER.call
    disabled_catalogs = (
        (
            "broker_execution.read.overview",
            "get_broker_execution_overview",
        ),
        (
            "broker_execution.read.order_catalog",
            "list_broker_execution_orders",
        ),
        (
            "broker_execution.read.connection_status",
            "get_broker_execution_connections",
        ),
        (
            "broker_execution.read.reconciliation_catalog",
            "list_broker_execution_reconciliations",
        ),
        (
            "broker_execution.read.audit_catalog",
            "list_broker_execution_audit",
        ),
    )
    for capability_key, handler_name in disabled_catalogs:
        assert handler_name in server_module.INTERNAL_GOVERNED_HANDLERS
        blocked = agom_capability_call(capability_key=capability_key, arguments={})
        assert blocked["status"] == "error"
        assert blocked["error"]["code"] == "capability_not_found"


def test_order_detail_handler_projects_a_closed_payload_without_event_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agomtradepro_mcp.registry.runtime_handlers.owners import broker_execution

    class _BrokerExecution:
        @staticmethod
        def get_order(_client_order_id):
            return _governed_order_detail()

    monkeypatch.setattr(
        broker_execution,
        "_client",
        lambda: SimpleNamespace(broker_execution=_BrokerExecution()),
    )

    result = broker_execution._internal_handler_broker_execution_order(
        "00000000-0000-0000-0000-000000000001"
    )

    assert "risk_snapshot" not in result
    assert "unexpected" not in result
    assert result["events"] == [
        {
            "event_id": "event-1",
            "event_type": "ORDER_REVIEWED",
            "status": "WAITING_APPROVAL",
            "occurred_at": "2026-08-13T11:20:00+00:00",
            "received_at": "2026-08-13T11:20:01+00:00",
        }
    ]


def test_order_detail_output_schema_is_closed_at_every_object_level() -> None:
    schema = (
        CapabilityRegistryLoader()
        .build_registry()["broker_execution.read.order_detail"]
        .output_schema
    )

    def assert_closed(value):
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            assert value["additionalProperties"] is False
            assert set(value["required"]) == set(value["properties"])
        for child in value.values():
            if isinstance(child, list):
                for item in child:
                    assert_closed(item)
            else:
                assert_closed(child)

    assert_closed(schema)


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
