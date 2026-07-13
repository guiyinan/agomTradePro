# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_pulse."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_pulse_current_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="pulse.read.current",
        summary="Read the current tactical pulse snapshot.",
        description="Return the current pulse dimensions, tactical composite score, and decision-safety contract.",
        owner_app="pulse",
        tags=("pulse", "macro", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_pulse_current",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="get_pulse_current", description="pulse current", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.pulse.read.current"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "pulse.read.current"
    assert governed.execution_target["replacement_for"] == ["get_pulse_current"]
    assert governed.semantic_key == "pulse.read.current"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_pulse_current"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "pulse.read.current"
    assert legacy.semantic_key == "pulse.read.current"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_pulse_history_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="pulse.read.history",
        summary="Read recent pulse history snapshots.",
        description="Return recent pulse observations for tactical trend analysis.",
        owner_app="pulse",
        tags=("pulse", "macro", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_pulse_history",),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name="get_pulse_history", description="pulse history", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.pulse.read.history"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "pulse.read.history"
    assert governed.execution_target["replacement_for"] == ["get_pulse_history"]
    assert governed.semantic_key == "pulse.read.history"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_pulse_history"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "pulse.read.history"
    assert legacy.semantic_key == "pulse.read.history"
    assert legacy.enabled_for_terminal is False
