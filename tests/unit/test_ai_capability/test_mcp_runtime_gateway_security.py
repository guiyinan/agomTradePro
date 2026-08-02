from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from apps.ai_capability.application import mcp_runtime_gateway as gateway
from apps.ai_capability.application.mcp_runtime_gateway import (
    McpRuntimeValidationError,
)
from apps.ai_capability.application.sync_use_cases import SyncCapabilitiesUseCase
from apps.ai_capability.application.use_cases import CapabilityExecutionDispatcher
from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    RoutingContext,
    SourceType,
)


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"Description for {name}",
        inputSchema={"type": "object"},
    )


def _install_fake_server_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    block_legacy_reload: bool = False,
) -> tuple[SimpleNamespace, Event, Event]:
    server_module = SimpleNamespace(server=SimpleNamespace(list_tools=lambda: []))
    legacy_reload_entered = Event()
    release_legacy_reload = Event()

    monkeypatch.setattr(gateway, "ensure_sdk_on_path", lambda: None)
    monkeypatch.setattr(gateway, "load_mcp_env_from_repo_config", lambda: None)
    monkeypatch.setattr(
        gateway.importlib,
        "import_module",
        lambda module_name: server_module,
    )

    def _reload(module: SimpleNamespace) -> SimpleNamespace:
        legacy_enabled = os.environ.get("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS") == "true"
        if block_legacy_reload and legacy_enabled and not legacy_reload_entered.is_set():
            legacy_reload_entered.set()
            assert release_legacy_reload.wait(timeout=5)
        tools = [_tool("agom_bootstrap")]
        if legacy_enabled:
            tools.append(_tool("legacy_write_tool"))
        module.server = SimpleNamespace(list_tools=lambda: tools)
        return module

    monkeypatch.setattr(gateway.importlib, "reload", _reload)
    monkeypatch.setattr(gateway, "run_awaitable_sync", lambda loader: loader())
    return server_module, legacy_reload_entered, release_legacy_reload


def test_core_tool_listing_overrides_and_restores_ambient_legacy_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_server_runtime(monkeypatch)
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", "true")

    core_tools = gateway.list_sdk_mcp_tools(include_legacy=False)
    legacy_tools = gateway.list_sdk_mcp_tools(include_legacy=True)

    assert [tool.name for tool in core_tools] == ["agom_bootstrap"]
    assert [tool.name for tool in legacy_tools] == [
        "agom_bootstrap",
        "legacy_write_tool",
    ]
    assert os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] == "true"


def test_core_listing_waits_for_legacy_reload_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, legacy_entered, release_legacy = _install_fake_server_runtime(
        monkeypatch,
        block_legacy_reload=True,
    )
    core_finished = Event()

    def _legacy_call() -> list[str]:
        return [tool.name for tool in gateway.list_sdk_mcp_tools(include_legacy=True)]

    def _core_call() -> list[str]:
        names = [tool.name for tool in gateway.list_sdk_mcp_tools(include_legacy=False)]
        core_finished.set()
        return names

    with ThreadPoolExecutor(max_workers=2) as executor:
        legacy_future = executor.submit(_legacy_call)
        assert legacy_entered.wait(timeout=5)
        core_future = executor.submit(_core_call)
        assert not core_finished.wait(timeout=0.1)
        release_legacy.set()

        assert legacy_future.result(timeout=5) == [
            "agom_bootstrap",
            "legacy_write_tool",
        ]
        assert core_future.result(timeout=5) == ["agom_bootstrap"]


def test_tool_listing_rejects_non_boolean_flag_before_runtime_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_sdk = Mock()
    monkeypatch.setattr(gateway, "ensure_sdk_on_path", ensure_sdk)

    with pytest.raises(
        McpRuntimeValidationError,
        match="mcp_include_legacy_must_be_boolean",
    ):
        gateway.list_sdk_mcp_tools(include_legacy=cast(bool, "false"))

    ensure_sdk.assert_not_called()


@pytest.mark.parametrize(
    "tools",
    [
        [_tool("duplicate"), _tool("duplicate")],
        [SimpleNamespace(name="bad tool", description="Bad", inputSchema={})],
        [SimpleNamespace(name="valid_tool", description="Valid", inputSchema={1: "bad"})],
        [SimpleNamespace(name="valid_tool", description="Valid", inputSchema=[])],
    ],
)
def test_tool_listing_rejects_malformed_dynamic_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tools: list[SimpleNamespace],
) -> None:
    server_module, _, _ = _install_fake_server_runtime(monkeypatch)
    monkeypatch.setattr(
        gateway.importlib,
        "reload",
        lambda module: module,
    )
    server_module.server = SimpleNamespace(list_tools=lambda: tools)

    with pytest.raises(McpRuntimeValidationError):
        gateway.list_sdk_mcp_tools()


def test_mcp_call_rejects_invalid_params_and_result_without_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk_call = Mock(return_value={"ok": True})
    monkeypatch.setattr(gateway, "_call_sdk_mcp_tool", sdk_call)

    for tool_name, params in (
        ("../admin", {}),
        ("agom_capability_call", {"nested": {1: "invalid-key"}}),
        ("agom_capability_call", {"score": float("nan")}),
        ("agom_capability_call", {"payload": "x" * 262_145}),
    ):
        with pytest.raises(McpRuntimeValidationError):
            gateway.call_sdk_mcp_tool(tool_name, params)

    sdk_call.assert_not_called()

    sdk_call.return_value = {"ok": True, "score": float("inf")}
    with pytest.raises(McpRuntimeValidationError, match="mcp_call_result_invalid"):
        gateway.call_sdk_mcp_tool("agom_capability_call", {})


def test_mcp_call_returns_detached_finite_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_result = {"ok": True, "result": {"items": [1, 2]}}
    sdk_call = Mock(return_value=raw_result)
    monkeypatch.setattr(gateway, "_call_sdk_mcp_tool", sdk_call)

    result = gateway.call_sdk_mcp_tool(
        "agom_capability_call",
        {"capability_key": "system.read.regime.current", "arguments": {}},
    )

    assert result == raw_result
    assert result is not raw_result
    sdk_call.assert_called_once_with(
        "agom_capability_call",
        {"capability_key": "system.read.regime.current", "arguments": {}},
        user_id=None,
        username="",
    )


def test_capability_dispatch_propagates_originating_user_to_mcp_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = CapabilityDefinition(
        capability_key="mcp_tool.equity.read.research_snapshot",
        source_type=SourceType.MCP_TOOL,
        source_ref="equity.read.research_snapshot",
        name="equity.read.research_snapshot",
        summary="Read persisted equity evidence",
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "equity.read.research_snapshot",
        },
    )
    context = RoutingContext(
        entrypoint="agent",
        user_id=7,
        session_id="session-1",
        context={"params": {"stock_code": "通富微电"}, "username": "researcher"},
    )
    sdk_call = Mock(return_value={"status": "completed", "result": {"stock_code": "002156.SZ"}})
    monkeypatch.setattr(
        "apps.ai_capability.application.use_cases._call_sdk_mcp_tool",
        sdk_call,
    )

    result = CapabilityExecutionDispatcher()._execute_mcp_tool(capability, context)

    assert result["result"]["result"]["stock_code"] == "002156.SZ"
    sdk_call.assert_called_once_with(
        "agom_capability_call",
        {
            "capability_key": "equity.read.research_snapshot",
            "arguments": {"stock_code": "通富微电"},
        },
        user_id=7,
        username="researcher",
    )


def test_validation_failure_does_not_fall_back_to_builtin_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = CapabilityDefinition(
        capability_key="mcp_tool.invalid",
        source_type=SourceType.MCP_TOOL,
        source_ref="invalid",
        name="invalid",
        summary="Invalid MCP request",
        execution_target={"type": "mcp_tool", "tool_name": "invalid tool"},
    )
    context = RoutingContext(
        entrypoint="agent",
        session_id="session-1",
        context={"params": {}},
    )
    builtin = Mock()
    monkeypatch.setattr(
        "apps.ai_capability.application.use_cases._call_sdk_mcp_tool",
        Mock(side_effect=McpRuntimeValidationError("mcp_tool_name_invalid")),
    )
    monkeypatch.setattr(
        "apps.ai_capability.application.use_cases.execute_builtin_tool",
        builtin,
    )

    result = CapabilityExecutionDispatcher()._execute_mcp_tool(capability, context)

    assert result == {
        "reply": "MCP tool request rejected.",
        "error_code": "mcp_request_invalid",
    }
    builtin.assert_not_called()


def test_capability_sync_failure_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    capability_repo = Mock()
    sync_log_repo = Mock()
    use_case = SyncCapabilitiesUseCase(
        capability_repo=capability_repo,
        sync_log_repo=sync_log_repo,
    )
    monkeypatch.setattr(
        use_case,
        "_sync_builtin",
        Mock(side_effect=RuntimeError("postgresql://admin:secret@internal/db")),
    )

    result = use_case.execute(source="builtin")

    assert result.error_count == 1
    assert result.summary == {"builtin": {"error": "capability_source_sync_failed"}}
    assert "secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    capability_repo.disable_missing.assert_not_called()
    sync_log_repo.save.assert_called_once()
