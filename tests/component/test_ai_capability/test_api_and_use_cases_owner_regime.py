# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_regime."""

from .api_and_use_cases_support import *


@pytest.mark.django_db
def test_sync_mcp_tools_discovers_builtin_registry_tools():
    pytest.importorskip("mcp")

    use_case = SyncCapabilitiesUseCase()

    result = use_case.execute(sync_type="incremental", source="mcp_tool")

    assert result.total_discovered >= 300

    rows = CapabilityCatalogModel.objects.filter(source_type="mcp_tool")
    assert rows.count() >= 300

    keys = set(rows.values_list("capability_key", flat=True))
    assert {
        "mcp_tool.ai_provider.read.provider_catalog",
        "mcp_tool.ai_provider.read.provider_detail",
        "mcp_tool.ai_provider.read.usage_logs",
        "mcp_tool.filter.read.indicator_catalog",
        "mcp_tool.filter.read.config_detail",
        "mcp_tool.prompt.read.template_catalog",
        "mcp_tool.prompt.read.chain_catalog",
        "mcp_tool.risk_center.read.floor",
        "mcp_tool.risk_center.read.template_catalog",
        "mcp_tool.risk_center.read.effective_policy",
        "mcp_tool.risk_center.read.account_policy",
        "mcp_tool.risk_center.read.exception_list",
        "mcp_tool.risk_center.read.pre_trade_check",
        "mcp_tool.risk_center.read.post_investment_check",
        "mcp_tool.risk_center.read.daily_report",
        "mcp_tool.risk_center.read.daily_report_history",
        "mcp_tool.data_center.read.indicator_catalog",
        "mcp_tool.data_center.read.macro_series",
        "mcp_tool.data_center.read.provider_catalog",
        "mcp_tool.data_center.read.provider_status",
        "mcp_tool.policy.read.events",
        "mcp_tool.policy.read.workbench.summary",
        "mcp_tool.policy.read.workbench.event_detail",
        "mcp_tool.policy.read.workbench.bootstrap",
        "mcp_tool.policy.read.workbench.items",
        "mcp_tool.policy.read.sentiment_gate.state",
        "mcp_tool.pulse.read.current",
        "mcp_tool.pulse.read.history",
        "mcp_tool.regime.read.navigator",
        "mcp_tool.regime.read.distribution",
        "mcp_tool.regime.read.history",
        "mcp_tool.system.read.policy.status",
        "mcp_tool.system.read.regime.current",
        "mcp_tool.system.read.task_monitor.statistics",
        "mcp_tool.task_monitor.read.celery_health",
        "mcp_tool.task_monitor.read.dashboard",
        "mcp_tool.task_monitor.read.task_list",
        "mcp_tool.task_monitor.read.task_status",
    }.issubset(keys)
    assert "mcp_tool.get_current_regime" in keys
    assert "mcp_tool.get_policy_status" in keys

    governed = rows.get(capability_key="mcp_tool.system.read.regime.current")
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"

    legacy = rows.get(capability_key="mcp_tool.get_current_regime")
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["legacy"] is True
    assert legacy.execution_target["replacement_capability_key"] == "system.read.regime.current"


def test_sync_mcp_tools_creates_governed_capability_entries_and_hides_legacy_tools():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="system.read.regime.current",
        summary="Read the current macro regime snapshot.",
        description="Return current regime metadata.",
        owner_app="regime",
        tags=("regime", "macro", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="safe",
        requires_confirmation=False,
        legacy_tool_names=("get_current_regime",),
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
                    name="get_current_regime", description="legacy read", inputSchema={}
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.system.read.regime.current"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "system.read.regime.current"
    assert governed.execution_target["replacement_for"] == ["get_current_regime"]
    assert governed.enabled_for_terminal is True
    assert governed.enabled_for_chat is False
    assert governed.enabled_for_agent is True
    assert governed.visibility.value == "public"
    assert governed.priority_weight == 10.0

    legacy = by_key["mcp_tool.get_current_regime"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["legacy"] is True
    assert legacy.execution_target["replacement_capability_key"] == "system.read.regime.current"
    assert legacy.enabled_for_terminal is False
    assert legacy.enabled_for_chat is False
    assert legacy.enabled_for_agent is False
    assert legacy.semantic_key == "system.read.regime.current"
    assert legacy.priority_weight == 0.1
