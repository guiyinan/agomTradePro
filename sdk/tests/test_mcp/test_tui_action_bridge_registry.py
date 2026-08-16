"""Tests for complete published-TUI action access through governed MCP."""

from __future__ import annotations

import asyncio

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.runtime_handlers.owners import terminal


def test_terminal_action_bridge_manifests_are_registered() -> None:
    registry = CapabilityRegistryLoader().build_registry()

    assert "terminal.search.user_actions" in registry
    assert "terminal.read.user_action_schema" in registry
    assert "terminal.read.user_action_result" in registry
    assert registry["terminal.read.user_action_result"].enabled is False
    write_manifest = registry["terminal.execute.user_action"]
    assert write_manifest.requires_confirmation is True
    assert write_manifest.idempotency == "required"


def test_decision_facing_broker_native_reads_are_not_discoverable() -> None:
    registry = CapabilityRegistryLoader().build_registry()
    blocked = {
        "broker_execution.read.overview",
        "broker_execution.read.order_catalog",
        "broker_execution.read.connection_status",
        "broker_execution.read.reconciliation_catalog",
        "broker_execution.read.audit_catalog",
    }

    assert all(registry[key].enabled is False for key in blocked)


def test_terminal_action_handlers_search_schema_and_block_unbound_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Client:
        def get(self, endpoint, params=None):
            calls.append(("GET", endpoint, params))
            if endpoint.endswith("/search/"):
                return {"actions": [{"action_key": "account.positions"}], "returned_count": 1}
            return {
                "action_key": "account.positions",
                "risk": "read",
                "requires_confirmation": False,
                "fields": [],
            }

        def post(self, endpoint, json=None):
            calls.append(("POST", endpoint, json))
            return {"business_summary": "持仓读取完成", "response": {"status_code": 200}}

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", Client)

    search = terminal._internal_handler_terminal_search_user_actions(query="持仓", limit=100)
    with pytest.raises(PermissionError, match="mcp_evidence_binding_required"):
        terminal._internal_handler_terminal_run_user_read_action("account.positions", {"limit": 5})

    assert search["returned_count"] == 1
    assert calls[0][2]["limit"] == 20
    assert all(call[0] != "POST" for call in calls)


def test_terminal_read_result_native_handler_is_explicitly_gated_in_core_only_mode() -> None:
    """Prove the unbound read-result bridge cannot execute through core MCP."""

    import agomtradepro_mcp.server as server_module

    assert "terminal_run_user_read_action" in server_module.INTERNAL_GOVERNED_HANDLERS
    agom_capability_call = server_module.CORE_DISPATCHER.call
    blocked = agom_capability_call(
        capability_key="terminal.read.user_action_result",
        arguments={"action_key": "account.positions", "params": {"limit": 5}},
    )

    assert blocked["status"] == "error"
    assert blocked["error"]["code"] == "capability_not_found"


def test_terminal_write_action_handler_previews_and_rejects_read_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    risk = {"value": "write"}

    class Client:
        def get(self, _endpoint, params=None):
            return {
                "action_key": "account.position.create",
                "risk": risk["value"],
                "requires_confirmation": True,
                "fields": [],
            }

        def post(self, _endpoint, json=None):
            return {"business_summary": "持仓已创建", "confirmed": json["confirmed"]}

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", Client)

    preview = terminal._internal_handler_terminal_execute_user_action(
        "account.position.create",
        {"asset_code": "000001.SZ"},
        idempotency_key="bridge-1",
        preview_only=True,
    )
    assert preview["preview_only"] is True

    committed = terminal._internal_handler_terminal_execute_user_action(
        "account.position.create",
        {"asset_code": "000001.SZ"},
    )
    assert committed["confirmed"] is True

    risk["value"] = "read"
    with pytest.raises(PermissionError):
        terminal._internal_handler_terminal_execute_user_action("account.position.create", {})


def test_core_dispatcher_confirms_terminal_write_action(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls = []

    def handler(**arguments):
        calls.append(arguments)
        return {"preview_only": arguments.get("preview_only", False)}

    monkeypatch.setitem(
        server_module.INTERNAL_GOVERNED_HANDLERS,
        "terminal_execute_user_action",
        handler,
    )
    staged = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "terminal.execute.user_action",
                "arguments": {
                    "action_key": "account.position.create",
                    "params": {"asset_code": "000001.SZ"},
                    "idempotency_key": "bridge-1",
                },
            },
        )
    )[1]

    assert staged["status"] == "confirmation_required"
    assert calls[0]["preview_only"] is True
    completed = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_confirmation_resume",
            {"confirmation_token": staged["confirmation_token"], "approve": True},
        )
    )[1]
    assert completed["ok"] is True
    assert calls[-1]["preview_only"] is False


@pytest.mark.parametrize(
    ("capability_key", "handler_ref", "arguments"),
    [
        (
            "terminal.search.user_actions",
            "terminal_search_user_actions",
            {"query": "持仓", "limit": 5},
        ),
        (
            "terminal.read.user_action_schema",
            "terminal_read_user_action_schema",
            {"action_key": "account.positions"},
        ),
    ],
)
def test_core_dispatcher_calls_native_terminal_read_handlers(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    handler_ref,
    arguments,
) -> None:
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_GOVERNED_HANDLERS,
        handler_ref,
        lambda **kwargs: {"source": "native-terminal-bridge", "arguments": kwargs},
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {"capability_key": capability_key, "arguments": arguments},
        )
    )[1]

    assert result["ok"] is True
    assert result["result"]["source"] == "native-terminal-bridge"
