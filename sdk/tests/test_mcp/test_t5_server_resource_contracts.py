"""T5 resource, prompt, and dispatch contracts for the MCP server."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import agomtradepro
from agomtradepro_mcp import server as server_module
from agomtradepro_mcp.agent_contracts import AgentContractConfigurationError


@pytest.fixture
def server_client(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Install a client and bypass RBAC while exercising resource formatting."""
    client = MagicMock()
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: client)
    monkeypatch.setattr(server_module, "enforce_resource_access", lambda _uri: None)
    monkeypatch.setattr(server_module, "enforce_prompt_access", lambda _name: None)
    return client


def test_dispatch_helpers_cover_registered_fallback_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal dispatch must reject recursion and surface missing registrations."""
    with pytest.raises(RuntimeError, match="recursively"):
        server_module._call_registered_tool(server_module.CORE_TOOL_NAMES[0], {})

    monkeypatch.setattr(server_module.server, "_tool_manager", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        server_module._call_registered_tool("legacy", {})

    manager = SimpleNamespace(_tools={})
    monkeypatch.setattr(server_module.server, "_tool_manager", manager)
    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "fallback",
        lambda value: {"value": value},
    )
    assert server_module._call_registered_tool("fallback", {"value": 3}) == {
        "value": 3
    }
    with pytest.raises(KeyError, match="not registered"):
        server_module._call_registered_tool("missing", {})

    manager._tools["broken"] = SimpleNamespace(fn=None)
    with pytest.raises(RuntimeError, match="no callable"):
        server_module._call_registered_tool("broken", {})
    manager._tools["ready"] = SimpleNamespace(fn=lambda value: value * 2)
    assert server_module._call_registered_tool("ready", {"value": 4}) == 8

    monkeypatch.setitem(
        server_module.INTERNAL_GOVERNED_HANDLERS,
        "ready",
        lambda value: value + 1,
    )
    assert server_module._call_internal_handler("ready", {"value": 4}) == 5
    with pytest.raises(KeyError, match="not registered"):
        server_module._call_internal_handler("missing", {})


def test_welcome_failure_and_rbac_guard_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup fallback and RBAC wrapping must tolerate unavailable components."""
    monkeypatch.setattr(
        server_module.AGENT_CONTRACT_STORE,
        "get_contract",
        MagicMock(side_effect=AgentContractConfigurationError("invalid")),
    )
    assert "Safe Startup" in server_module._build_welcome_message()

    monkeypatch.setattr(server_module.server, "_tool_manager", None)
    server_module.apply_tool_rbac_guards()

    def original(value: object) -> object:
        return value

    tools = {
        "ready": SimpleNamespace(fn=original),
        "missing": SimpleNamespace(fn=None),
    }
    monkeypatch.setattr(
        server_module.server,
        "_tool_manager",
        SimpleNamespace(_tools=tools),
    )
    wrapper = MagicMock(side_effect=lambda name, function: (name, function))
    monkeypatch.setattr(server_module, "wrap_tool_with_rbac_and_audit", wrapper)
    server_module.apply_tool_rbac_guards()
    assert tools["ready"].fn == ("ready", original)
    assert tools["missing"].fn is None


def test_regime_policy_and_contract_resources(
    server_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core resources must format SDK values and contract catalogs."""
    server_client.regime.get_current.return_value = SimpleNamespace(
        dominant_regime="recovery",
        growth_level="up",
        inflation_level="down",
        observed_at=date(2026, 7, 25),
        growth_indicator="PMI",
        growth_value=51.2,
        inflation_indicator="CPI",
        inflation_value=1.0,
    )
    event = SimpleNamespace(event_date=date(2026, 7, 24), description="rate decision")
    server_client.policy.get_status.return_value = SimpleNamespace(
        current_gear="P1",
        observed_at=datetime(2026, 7, 25, tzinfo=UTC),
        recent_events=[event],
    )
    assert "PMI (51.2)" in server_module.resource_regime_current()
    assert "rate decision" in server_module.resource_policy_status()

    monkeypatch.setattr(server_module, "_build_welcome_message", lambda: "welcome")
    assert server_module.resource_welcome() == "welcome"
    monkeypatch.setattr(
        server_module.AGENT_CONTRACT_STORE,
        "list_playbooks",
        lambda: [{"name": "research"}],
    )
    assert "research" in server_module.resource_agent_playbooks()


def test_context_resources_and_workflow_prompts(
    server_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Context resources and workflow prompts must preserve requested domains."""
    server_client.agent_context.get_context_snapshot.return_value = {
        "domain": "research",
        "generated_at": "2026-07-25T00:00:00Z",
        "regime_summary": {
            "status": "ok",
            "dominant_regime": "recovery",
            "growth_level": "up",
            "inflation_level": "down",
        },
        "policy_summary": {"status": "ok", "current_gear": "P1"},
        "portfolio_summary": {"status": "ok", "position_count": 2},
        "active_signals_summary": {"status": "ok", "active_count": 3},
        "open_decisions_summary": {},
        "risk_alerts_summary": {},
        "task_health_summary": {
            "active_tasks": 1,
            "needs_human": 2,
            "failed_tasks": 0,
        },
        "data_freshness_summary": {},
    }
    snapshot = server_module._format_context_snapshot("research")
    assert "Dominant: recovery" in snapshot
    assert "Positions: 2" in snapshot
    assert server_module.resource_context_research()
    assert server_module.resource_context_monitoring()
    assert server_module.resource_context_decision()
    assert server_module.resource_context_execution()
    assert server_module.resource_context_ops()

    render = MagicMock(return_value="prompt")
    monkeypatch.setattr(server_module.AGENT_CONTRACT_STORE, "render_prompt", render)
    assert server_module.prompt_analyze_macro_environment() == "prompt"
    assert server_module.prompt_check_signal_eligibility("A", "logic") == "prompt"
    assert server_module.prompt_run_research_workflow("equity") == "prompt"
    assert server_module.prompt_run_monitoring_workflow("freshness") == "prompt"
    assert server_module.prompt_run_decision_workflow("review") == "prompt"
    assert server_module.prompt_run_execution_workflow("execute") == "prompt"
    assert server_module.prompt_run_ops_workflow("health") == "prompt"


def test_default_account_id_and_account_resources(
    server_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-account resources must support environment and discovery lookup."""
    monkeypatch.setenv("AGOMTRADEPRO_DEFAULT_ACCOUNT_ID", "9")
    assert server_module._get_default_account_id(server_client) == 9
    monkeypatch.setenv("AGOMTRADEPRO_DEFAULT_ACCOUNT_ID", "invalid")
    server_client.account.list_accounts.return_value = [{"account_id": 7}]
    assert server_module._get_default_account_id(server_client) == 7
    server_client.account.list_accounts.return_value = [{"id": 8}]
    assert server_module._get_default_account_id(server_client) == 8
    server_client.account.list_accounts.return_value = []
    assert server_module._get_default_account_id(server_client) is None

    monkeypatch.setenv("AGOMTRADEPRO_DEFAULT_ACCOUNT_ID", "7")
    server_client.account.get_account.return_value = {
        "account_name": "main",
        "account_type": "cash",
        "total_value": 100,
        "current_cash": 20,
    }
    position = {
        "asset_code": "A",
        "quantity": 10,
        "avg_cost": 2,
        "current_price": 3,
        "unrealized_pnl": 10,
    }
    server_client.account.get_account_positions.return_value = [position]
    server_client.account.get_account_performance.return_value = {
        "total_trades": 3,
        "performance": {"total_return": 0.1, "max_drawdown": 0.02},
    }
    server_client.get.return_value = {
        "trades": [
            {
                "execution_time": "2026-07-25",
                "action": "buy",
                "asset_code": "A",
                "quantity": 10,
                "price": 2,
            }
        ]
    }
    assert "账户名称: main" in server_module.resource_account_summary()
    assert "A | 持仓: 10" in server_module.resource_account_positions()
    assert "buy A 10 @ 2" in server_module.resource_account_recent_transactions()

    server_client.account.get_account_positions.return_value = []
    assert "当前无持仓" in server_module.resource_account_positions()
    server_client.get.return_value = []
    assert "暂无交易记录" in server_module.resource_account_recent_transactions()
